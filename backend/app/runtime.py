"""Independent camera workers, bounded capture pumps and result persistence."""

from dataclasses import dataclass, field
import logging
import queue
import threading
import time

import cv2

from app.annotate import annotate
from engine.engine import RuleEngine

log = logging.getLogger('policylens.runtime')


@dataclass
class CameraRuntime:
    camera: object
    stop: threading.Event = field(default_factory=threading.Event)
    inbox: queue.Queue = field(default_factory=lambda: queue.Queue(2))
    pipeline: object = None
    thread: object = None
    reader: object = None
    stopping_pipeline: bool = False
    status: str = 'connecting'
    error: str | None = None
    fps: float = 0
    last_frame_ts: float | None = None
    states: list = field(default_factory=list)
    jpeg: bytes | None = None
    version: int = 0


class Monitor:
    def __init__(self, settings, store, hub, scheduler, writer, pipeline_factory, *, retry_seconds=2):
        self.settings, self.store, self.hub = settings, store, hub
        self.scheduler, self.writer = scheduler, writer
        self.pipeline_factory, self.retry_seconds = pipeline_factory, retry_seconds
        self.control_lock = threading.RLock()
        self._lock = threading.RLock()
        self._active = False
        self._cameras = {}

    @property
    def running(self):
        with self._lock:
            return self._active or any(
                (runtime.thread is not None and runtime.thread.is_alive())
                or (runtime.reader is not None and runtime.reader.is_alive())
                for runtime in self._cameras.values())

    def invalidate_preview(self):
        with self._lock:
            self._cameras.clear()

    def snapshot(self):
        with self._lock:
            cameras = []
            states = []
            for camera in self.settings.snapshot().cameras:
                runtime = self._cameras.get(camera.id)
                cameras.append(self._camera_status(runtime) if runtime else {
                    'camera_id': camera.id, 'status': 'offline', 'fps': 0,
                    'last_frame_ts': None, 'error': None})
                if runtime:
                    states.extend(runtime.states)
            return {'running': self.running, 'cameras': cameras, 'rule_states': list(states)}

    @staticmethod
    def _camera_status(runtime):
        return {'camera_id': runtime.camera.id, 'status': runtime.status, 'fps': runtime.fps,
                'last_frame_ts': runtime.last_frame_ts, 'error': runtime.error}

    def _status(self, runtime, status, error=None):
        with self._lock:
            changed = runtime.status != status or runtime.error != error
            runtime.status, runtime.error = status, error
            if status != 'online':
                runtime.fps = 0
            data = self._camera_status(runtime)
        if changed:
            self.hub.publish('camera_status', data)

    def start(self):
        with self.control_lock:
            if self._active:
                return
            if self.running:
                raise RuntimeError('A previous camera worker is still stopping')
            config = self.settings.snapshot()
            if not config.cameras:
                raise ValueError('Configure at least one camera before monitoring')
            with self._lock:
                self._active = True
                self._cameras = {camera.id: CameraRuntime(camera) for camera in config.cameras}
                runtimes = list(self._cameras.values())
            for runtime in runtimes:
                runtime.thread = threading.Thread(target=self._run, args=(runtime, config),
                    daemon=True, name=f'camera-{runtime.camera.id}')
                runtime.thread.start()
            self.hub.publish('monitor_status', {'running': True})

    def stop(self):
        with self.control_lock:
            with self._lock:
                self._active = False
                runtimes = list(self._cameras.values())
            for runtime in runtimes:
                runtime.stop.set()
                if runtime.pipeline is not None and not runtime.stopping_pipeline:
                    runtime.stopping_pipeline = True
                    def request_stop(pipe=runtime.pipeline):
                        try:
                            pipe.stop()
                        except Exception:
                            log.warning('Camera stop failed')
                    threading.Thread(target=request_stop, daemon=True).start()
            deadline = time.monotonic() + 6
            for runtime in runtimes:
                for thread in (runtime.thread, runtime.reader):
                    if thread is not None:
                        thread.join(max(0, deadline - time.monotonic()))
            if self.running:
                raise RuntimeError('A camera worker is still stopping; retry stop shortly')
            self.hub.publish('monitor_status', {'running': False})

    @staticmethod
    def _put(runtime, message):
        while not runtime.stop.is_set():
            try:
                runtime.inbox.put(message, timeout=0.05)
                return
            except queue.Full:
                pass

    def _read(self, runtime):
        pipe = None
        try:
            pipe = self.pipeline_factory(runtime.camera)
            with self._lock:
                runtime.pipeline = pipe
                runtime.stopping_pipeline = False
            for image, frame in pipe.frames():
                self._put(runtime, ('frame', image, frame))
                if runtime.stop.is_set():
                    break
            self._put(runtime, ('ended' if runtime.camera.source.startswith('clip:') else 'error', None, None))
        except Exception:
            # Never expose camera URL credentials or provider exception text.
            self._put(runtime, ('error', None, None))
        finally:
            if pipe is not None:
                try:
                    pipe.stop()
                except Exception:
                    log.warning('Camera cleanup failed camera=%s', runtime.camera.id)

    def _save(self, alert):
        if self.store.save(alert):
            self.hub.publish('alert', alert.model_dump(mode='json'))

    def _collect(self, engine):
        for alert in engine.poll_verifications():
            self._save(alert)
        for patch in engine.poll_evidence():
            updated = self.store.apply_evidence(patch)
            self.hub.publish('alert_updated', updated.model_dump(mode='json'))

    def _run(self, runtime, config):
        engine = RuleEngine(runtime.camera.id, config.zones, config.rules,
                            scheduler=self.scheduler, evidence_writer=self.writer)
        reconnect_at, ended = 0, False
        last_publish, window_start, processed = 0, time.monotonic(), 0
        try:
            while not runtime.stop.is_set():
                try:
                    now = time.monotonic()
                    if (runtime.reader is None or not runtime.reader.is_alive()) and not ended and now >= reconnect_at:
                        engine.reset()
                        self._status(runtime, 'connecting')
                        runtime.reader = threading.Thread(target=self._read, args=(runtime,), daemon=True,
                                                          name=f'capture-{runtime.camera.id}')
                        runtime.reader.start()
                        # Prevent a restart until an EOF/error message is consumed.
                        reconnect_at = float('inf')
                    try:
                        kind, image, tf = runtime.inbox.get(timeout=0.05)
                    except queue.Empty:
                        kind = None
                    if kind == 'frame':
                        if runtime.last_frame_ts is not None and tf.ts < runtime.last_frame_ts:
                            engine.reset()
                        states, alerts = engine.update(image, tf)
                        for alert in alerts:
                            self._save(alert)
                        view = annotate(image, config.zones, tf, states)
                        ok, jpeg = cv2.imencode('.jpg', view)
                        with self._lock:
                            runtime.last_frame_ts = tf.ts
                            if ok:
                                runtime.jpeg = jpeg.tobytes()
                                runtime.version += 1
                        self._status(runtime, 'online')
                        processed += 1
                    elif kind == 'error':
                        self._status(runtime, 'offline', 'Camera source unavailable; retrying')
                        engine.reset()
                        reconnect_at = now + self.retry_seconds
                    elif kind == 'ended':
                        ended = True
                        for alert in engine.drain_verifications():
                            self._save(alert)
                        for patch in engine.drain_evidence():
                            updated = self.store.apply_evidence(patch)
                            self.hub.publish('alert_updated', updated.model_dump(mode='json'))
                        self._status(runtime, 'offline', 'Recorded source ended')
                    self._collect(engine)
                    if runtime.pipeline is not None and getattr(runtime.pipeline, 'status', None) == 'offline':
                        self._status(runtime, 'offline', 'Camera source unavailable')
                    if now - last_publish >= 0.2:
                        states = [] if ended else [state.model_dump(mode='json') for state in engine.snapshot_states()]
                        with self._lock:
                            runtime.states = states
                        self.hub.publish('state', {'camera_id': runtime.camera.id,
                            'ts': runtime.last_frame_ts or 0, 'rule_states': states})
                        last_publish = now
                    if now - window_start >= 1:
                        fps = processed / (now - window_start)
                        with self._lock:
                            runtime.fps = fps if runtime.status == 'online' else 0
                        log.info('Camera camera=%s fps=%.1f', runtime.camera.id, fps)
                        self.hub.publish('camera_status', self._camera_status(runtime))
                        processed, window_start = 0, now
                except Exception:
                    log.warning('Camera iteration failed camera=%s', runtime.camera.id)
                    self._status(runtime, 'offline', 'Camera observation unavailable')
                    runtime.stop.wait(0.05)
        finally:
            try:
                for alert in engine.drain_verifications():
                    self._save(alert)
                for patch in engine.drain_evidence():
                    updated = self.store.apply_evidence(patch)
                    self.hub.publish('alert_updated', updated.model_dump(mode='json'))
            except Exception:
                log.warning('Evidence drain failed camera=%s', runtime.camera.id)
            engine.reset()
            with self._lock:
                runtime.states = []
            self._status(runtime, 'offline')

    def latest(self, camera_id):
        with self._lock:
            runtime = self._cameras.get(camera_id)
            return (runtime.jpeg, runtime.version) if runtime else (None, 0)

    def preview(self, camera):
        cached, _ = self.latest(camera.id)
        if cached:
            return cached
        if self.running:
            return None
        # Configure/draw zones before monitoring starts. This performs no rule evaluation.
        pipe = self.pipeline_factory(camera)
        stream = pipe.frames()
        try:
            image, _ = next(stream)
            ok, jpeg = cv2.imencode('.jpg', image)
            if not ok:
                return None
            with self._lock:
                runtime = self._cameras.setdefault(camera.id, CameraRuntime(camera))
                runtime.jpeg, runtime.version = jpeg.tobytes(), runtime.version + 1
                runtime.status = 'offline'
            return jpeg.tobytes()
        finally:
            pipe.stop()
            if hasattr(stream, 'close'):
                stream.close()
