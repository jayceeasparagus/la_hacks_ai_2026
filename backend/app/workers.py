"""One thread per camera: source -> adapter -> RuleEngine -> evidence/store -> broadcast.

Nothing may kill a worker. Each frame is processed inside its own try/except; a
source that fails or ends is stopped, shown offline and rebuilt after 2 s with a
fresh engine session. Replay sources that finish stay offline ('replay ended').
A small monitor thread publishes `camera_status` whenever a camera's status
changes, which also covers sources that block while their camera is offline.

New rules can be swapped into running workers (`MonitorManager.apply_rules`): each
camera keeps its source and starts a fresh engine session with the new rules.
Looping demo sources replay the same objects, so they alert once per rule and track
per applied policy instead of on every loop.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import numpy as np

from app.adapter import ContractAdapter
from app.evidence import EvidenceWriter
from app.models import Alert, Camera, Rule, RuleState, TrackFrame, Zone
from app.render import annotate, encode_jpeg
from app.settings import MAX_CAMERAS
from app.sources import SourceError, build_source
from app.verdicts import CachedVerdicts
from engine.engine import RuleEngine, _default_verifier
from engine.verification import VerificationScheduler
from store.db import AlertStore

log = logging.getLogger('policylens.workers')

REBUILD_SECONDS = 2.0
STATE_INTERVAL = 0.2        # at most 5 `state` messages per second per camera
FPS_LOG_SECONDS = 10.0
STALE_FPS_SECONDS = 2.0     # no frame for this long -> fps 0
STATUS_POLL_SECONDS = 0.25
ERROR_LOG_SECONDS = 5.0

Publish = Callable[[str, object], None]
SourceFactory = Callable[[Camera], object]


def _safe_error(error: BaseException) -> str:
    """Errors shown to users; SourceError messages are written to be safe."""
    if isinstance(error, SourceError):
        return str(error)
    return f'source failed ({type(error).__name__}); retrying'


class CameraWorker(threading.Thread):
    def __init__(self, camera: Camera, zones: list[Zone], rules: list[Rule], *,
                 source_factory: SourceFactory, store: AlertStore, evidence: EvidenceWriter,
                 publish: Publish, verifier=None, scheduler=None, rebuild_seconds: float = REBUILD_SECONDS,
                 verdict_lookup=None):
        super().__init__(name=f'camera-{camera.id}', daemon=True)
        self.camera = camera
        self.camera_id = camera.id
        self.zones = [zone for zone in zones if zone.camera_id == camera.id]
        self._all_zones = zones
        self._engine_options = {'verifier': verifier, 'scheduler': scheduler, 'verdict_lookup': verdict_lookup}
        self.rules = {rule.id: rule for rule in rules}
        self.engine = RuleEngine(camera.id, zones, rules, **self._engine_options)
        self._alerted: set[tuple[str, int]] = set()  # (rule, track) already alerted, for looping sources
        self._engine_lock = threading.RLock()
        self._source_offline = False
        self.adapter = ContractAdapter(camera.id)
        self.source_factory = source_factory
        self.store = store
        self.evidence = evidence
        self.publish = publish
        self.rebuild_seconds = rebuild_seconds
        self.source = None
        self._stopping = threading.Event()
        self._lock = threading.Lock()          # latest frame / status fields
        self._alert_lock = threading.Lock()    # store.add before evidence store.update
        self._state = 'connecting'             # worker-level status when no source is active
        self._error: str | None = None
        self._last_frame_ts: float | None = None
        self._last_frame_wall: float | None = None
        self._fps = 0.0
        self._fps_window = (time.monotonic(), 0)
        self._fps_log = (time.monotonic(), 0)
        self._last_state_pub = 0.0
        self._rule_states: list[RuleState] = []
        self._latest: tuple[int, np.ndarray, TrackFrame, list[RuleState], dict] | None = None
        self._seq = 0
        self._raw_cache: tuple[int, bytes] | None = None
        self._annotated_cache: tuple[int, bytes] | None = None
        self._last_error_log = 0.0
        self.frames_processed = 0
        self.alerts_stored = 0

    # Status ---------------------------------------------------------------------

    def status(self) -> dict:
        """A CameraStatus dict."""
        with self._lock:
            source, state, error = self.source, self._state, self._error
            last_ts, last_wall, fps = self._last_frame_ts, self._last_frame_wall, self._fps
        if source is not None and state == 'active':
            try:
                state = source.status
                error = source.error if state == 'offline' else None
            except Exception:
                state, error = 'offline', 'source status unavailable'
        if state not in ('online', 'offline', 'connecting'):
            state = 'offline'
        if state != 'online' or last_wall is None or time.monotonic() - last_wall > STALE_FPS_SECONDS:
            fps = 0.0
        return {'camera_id': self.camera_id, 'status': state, 'fps': round(fps, 1),
                'last_frame_ts': last_ts, 'error': error}

    def rule_states(self) -> list[RuleState]:
        with self._lock:
            return list(self._rule_states)

    def _set_state(self, state: str, error: str | None = None) -> None:
        with self._lock:
            self._state, self._error = state, error

    # Frames for the HTTP routes ------------------------------------------------------

    def raw_jpeg(self) -> bytes | None:
        with self._lock:
            latest, cache = self._latest, self._raw_cache
        if latest is None:
            return None
        if cache is not None and cache[0] == latest[0]:
            return cache[1]
        data = encode_jpeg(latest[1])
        if data is not None:
            with self._lock:
                self._raw_cache = (latest[0], data)
        return data

    def annotated_jpeg(self) -> bytes | None:
        with self._lock:
            latest, cache = self._latest, self._annotated_cache
        if latest is None:
            return None
        if cache is not None and cache[0] == latest[0]:
            return cache[1]
        seq, image, tf, states, verdicts = latest
        data = encode_jpeg(annotate(image, self.zones, tf, states, self.rules, verdicts))
        if data is not None:
            with self._lock:
                self._annotated_cache = (seq, data)
        return data

    # Lifecycle ---------------------------------------------------------------------------

    def set_rules(self, rules: list[Rule]) -> None:
        """Swap in new rules without touching the source: a fresh engine session starts now.

        Pending checks of the old rules are abandoned; stored alerts stay as they are.
        """
        engine = RuleEngine(self.camera_id, self._all_zones, rules, **self._engine_options)
        with self._engine_lock:
            old, self.engine = self.engine, engine
            self.rules = {rule.id: rule for rule in rules}
            self._alerted.clear()
        try:
            old.close()
        except Exception:
            log.exception('[%s] engine close failed', self.camera_id)
        self._publish_rule_states([], force=True)
        log.info('[%s] now watching %d rule(s)', self.camera_id, len(engine.rules))

    def stop(self) -> None:
        self._stopping.set()
        source = self.source
        if source is not None:
            try:
                source.stop()
            except Exception:
                log.exception('[%s] source stop failed', self.camera_id)

    def close(self) -> None:
        try:
            with self._engine_lock:
                self.engine.close()
        except Exception:
            log.exception('[%s] engine close failed', self.camera_id)

    def run(self) -> None:
        while not self._stopping.is_set():
            source = None
            try:
                self._set_state('connecting')
                source = self.source_factory(self.camera)
                with self._lock:
                    self.source = source
                    self._state = 'active'
                if self._stopping.is_set():
                    break
                with self._engine_lock:
                    self.adapter.reset()
                    self.engine.reset()
                for image, raw in source.frames():
                    if self._stopping.is_set():
                        break
                    self._process(image, raw)
                if self._stopping.is_set():
                    break
                if getattr(source, 'ended', False):
                    with self._engine_lock:
                        # Give in-flight checks their full budget; a real Gemini check can take ~12 s.
                        scheduler = self.engine.scheduler
                        drain_s = (scheduler.timeout if scheduler is not None else 5) + 2
                        for alert in self.engine.drain(timeout=drain_s):
                            self._handle_alert(alert, time.monotonic())
                    self._set_state('offline', getattr(source, 'error', None) or 'source ended')
                    log.info('[%s] source ended: %s', self.camera_id, self._error)
                    self._publish_rule_states([], force=True)
                    self._stopping.wait()
                    break
                error = getattr(source, 'error', None) or 'source stopped; reconnecting'
            except Exception as exc:
                error = _safe_error(exc)
                log.warning('[%s] camera source failed: %s', self.camera_id, error,
                            exc_info=not isinstance(exc, SourceError))
            finally:
                if source is not None:
                    try:
                        source.stop()
                    except Exception:
                        log.exception('[%s] source stop failed', self.camera_id)
                with self._lock:
                    self.source = None
            if self._stopping.is_set():
                break
            self._set_state('offline', error)
            self._publish_rule_states([], force=True)
            try:
                with self._engine_lock:
                    self.engine.reset()
            except Exception:
                log.exception('[%s] engine reset failed', self.camera_id)
            self._stopping.wait(self.rebuild_seconds)

    # Per frame ----------------------------------------------------------------------

    def poll_pending(self, status):
        # Poll even when a camera is blocked waiting for its next frame.
        if not self._engine_lock.acquire(blocking=False):
            return
        try:
            if self.source is not None:
                status = self.status()
            if status['status'] == 'offline' and not self._source_offline:
                self.engine.reset()
                self.adapter.reset()
                self._source_offline = True
                with self._lock:
                    self._last_frame_ts = None
                self._publish_rule_states([], force=True)
            elif status['status'] == 'online':
                self._source_offline = False
            if status['status'] == 'online':
                for alert in self.engine.poll_verifications():
                    self._handle_alert(alert, time.monotonic())
                self._publish_rule_states(self.engine.snapshot_states())
        finally:
            self._engine_lock.release()

    def _process(self, image, raw) -> None:
        with self._engine_lock:
            self._process_locked(image, raw)

    def _process_locked(self, image, raw) -> None:
        received = time.monotonic()
        try:
            tf, restarted = self.adapter.convert(raw)
            if tf is None:
                return
            if restarted:
                self.engine.reset()
            states, alerts = self.engine.update(image, tf)
            verdicts = self.engine.verdicts()
            self.frames_processed += 1
            self._count_frame(received)
            with self._lock:
                self._seq += 1
                self._latest = (self._seq, image, tf, states, verdicts)
                self._last_frame_ts, self._last_frame_wall = tf.ts, received
                self._rule_states = states
            for alert in alerts:
                self._handle_alert(alert, received)
            self._publish_rule_states(states, ts=tf.ts)
        except Exception:
            now = time.monotonic()
            if now - self._last_error_log >= ERROR_LOG_SECONDS:
                self._last_error_log = now
                log.exception('[%s] frame processing failed; continuing', self.camera_id)

    def _count_frame(self, now: float) -> None:
        start, count = self._fps_window
        count += 1
        if now - start >= 1.0:
            self._fps = count / (now - start)
            start, count = now, 0
        self._fps_window = (start, count)
        log_start, log_count = self._fps_log
        log_count += 1
        if now - log_start >= FPS_LOG_SECONDS:
            log.info('[%s] %.1f fps over the last %.0f s', self.camera_id,
                     log_count / (now - log_start), now - log_start)
            log_start, log_count = now, 0
        self._fps_log = (log_start, log_count)

    def _publish_rule_states(self, states: list[RuleState], ts: float | None = None,
                             force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_state_pub < STATE_INTERVAL:
            return
        self._last_state_pub = now
        if force:
            with self._lock:
                self._rule_states = list(states)
                ts = self._last_frame_ts if ts is None else ts
        self.publish('state', {'camera_id': self.camera_id, 'ts': ts or 0.0, 'rule_states': states})

    def _handle_alert(self, alert: Alert, received: float) -> None:
        frame = self.engine.pop_alert_frame(alert.id)
        recent = self.engine.pop_alert_clip(alert.id)
        snapshot_ts = self.engine.pop_alert_frame_ts(alert.id)
        if getattr(self.source, 'loops', False):
            # A looping demo clip shows the same people again: alert once per rule and track.
            key = (alert.rule_id, alert.track_id)
            if key in self._alerted:
                return
            self._alerted.add(key)
        with self._alert_lock:
            alert = self.evidence.submit(alert, frame, recent, on_done=self._evidence_done, snapshot_ts=snapshot_ts)
            if not self.store.add(alert):
                log.warning('[%s] duplicate alert id %s ignored', self.camera_id, alert.id)
                return
            self.alerts_stored += 1
            self.publish('alert', alert)
        log.info('[%s] alert %s (%s) stored; latency %.0f ms from frame to store',
                 self.camera_id, alert.id, alert.title, (time.monotonic() - received) * 1000)

    def _evidence_done(self, updated: Alert) -> None:
        with self._alert_lock:
            stored = self.store.update(updated)
            if stored is not None:
                self.publish('alert_updated', stored)


class MonitorManager:
    """Starts and stops the camera workers built from the saved configuration."""

    def __init__(self, settings, store: AlertStore, evidence: EvidenceWriter, publish: Publish, *,
                 verifier=None, source_factory: SourceFactory | None = None,
                 rebuild_seconds: float = REBUILD_SECONDS, cached_verdicts: CachedVerdicts | None = None):
        self.settings = settings
        self.cached_verdicts = cached_verdicts
        self.store = store
        self.evidence = evidence
        self.publish = publish
        self.verifier = verifier
        self.source_factory = source_factory
        self.rebuild_seconds = rebuild_seconds
        self.scheduler = None
        self.workers: dict[str, CameraWorker] = {}
        self.running = False
        self._lock = threading.RLock()
        self._monitor: threading.Thread | None = None
        self._monitor_stop = threading.Event()

    def start(self) -> bool:
        """Idempotent. Raises ValueError if the saved configuration cannot be monitored."""
        with self._lock:
            if self.running:
                return True
            if any(worker.is_alive() for worker in self.workers.values()):
                raise ValueError('Previous camera workers are still stopping')
            if self.scheduler is None:
                self.scheduler = VerificationScheduler(self.verifier or _default_verifier)
            cameras = self.settings.cameras()[:MAX_CAMERAS]
            zones, rules = self.settings.zones(), self.settings.rules()
            multi = len(cameras) > 1
            factory = self.source_factory or (lambda camera: build_source(camera, multi_camera=multi))
            workers = {}
            try:
                for camera in cameras:
                    lookup = self.cached_verdicts.lookup(camera.id) if self.cached_verdicts else None
                    workers[camera.id] = CameraWorker(
                        camera, zones, rules, source_factory=factory, store=self.store,
                        evidence=self.evidence, publish=self.publish, verifier=self.verifier, scheduler=self.scheduler,
                        rebuild_seconds=self.rebuild_seconds, verdict_lookup=lookup)
            except Exception:
                for worker in workers.values():
                    worker.close()
                raise
            self.workers = workers
            self.running = True
            for worker in workers.values():
                worker.start()
            self._monitor_stop = threading.Event()
            self._monitor = threading.Thread(target=self._watch, args=(self._monitor_stop,),
                                             name='camera-status', daemon=True)
            self._monitor.start()
            log.info('Monitoring started for %d camera(s): %s', len(workers), ', '.join(workers) or '-')
        self.publish('monitor_status', {'running': True})
        return True

    def stop(self, timeout: float = 5.0) -> bool:
        """Idempotent; joins the worker threads and closes their engines."""
        with self._lock:
            if not self.running:
                return False
            workers = self.workers
            self.running = False
            self._monitor_stop.set()
            for worker in workers.values():
                worker.stop()
            deadline = time.monotonic() + timeout
            for worker in workers.values():
                worker.join(max(0.1, deadline - time.monotonic()))
                if worker.is_alive():
                    log.warning('[%s] worker did not stop within %.0f s', worker.camera_id, timeout)
                worker.close()
            if self._monitor is not None:
                self._monitor.join(1.0)
                self._monitor = None
            self.workers = {key: worker for key, worker in workers.items() if worker.is_alive()}
            log.info('Monitoring stopped')
        self.publish('monitor_status', {'running': False})
        for status in self.statuses():
            self.publish('camera_status', status)
        for camera_id in workers:
            self.publish('state', {'camera_id': camera_id, 'ts': 0.0, 'rule_states': []})
        return True

    def apply_rules(self, rules: list[Rule]) -> None:
        """Running cameras switch to `rules` at once (validated and saved by the caller)."""
        with self._lock:
            if not self.running:
                return
            for worker in self.workers.values():
                worker.set_rules(rules)

    def close(self):
        self.stop()
        if self.scheduler is not None:
            self.scheduler.close(wait=False)
            self.scheduler = None

    def worker(self, camera_id: str) -> CameraWorker | None:
        return self.workers.get(camera_id)

    def statuses(self) -> list[dict]:
        workers = dict(self.workers)
        if self.running:
            return [worker.status() for worker in workers.values()]
        try:
            cameras = self.settings.cameras()
        except Exception:
            cameras = []
        return [{'camera_id': camera.id, 'status': 'offline', 'fps': 0.0, 'last_frame_ts': None,
                 'error': None} for camera in cameras]

    def rule_states(self) -> list[RuleState]:
        states = []
        for worker in list(self.workers.values()):
            states.extend(worker.rule_states())
        return states

    def snapshot(self) -> dict:
        return {'running': self.running, 'cameras': self.statuses(), 'rule_states': self.rule_states()}

    def _watch(self, stop: threading.Event) -> None:
        last: dict[str, tuple] = {}
        last_fps: dict[str, tuple[float, float]] = {}
        while not stop.is_set():
            for worker in list(self.workers.values()):
                try:
                    status = worker.status()
                    worker.poll_pending(status)
                    key = (status['status'], status['error'])
                    now = time.monotonic()
                    fps_sent, fps_at = last_fps.get(worker.camera_id, (-1.0, 0.0))
                    fps_changed = abs(status['fps'] - fps_sent) >= 1.0 and now - fps_at >= 2.0
                    if last.get(worker.camera_id) != key or fps_changed:
                        last[worker.camera_id] = key
                        last_fps[worker.camera_id] = (status['fps'], now)
                        if stop.is_set():
                            return
                        self.publish('camera_status', status)
                except Exception:
                    log.exception('Camera status check failed')
            stop.wait(STATUS_POLL_SECONDS)
