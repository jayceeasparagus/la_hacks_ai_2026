"""Camera-local temporal rule engine. All timing uses source timestamps.

Persistent rules alert from timing alone. Attribute rules time the same way, then
send one padded crop per incident to the crop verifier without blocking updates.
"""

from collections import OrderedDict
from concurrent.futures import (FIRST_COMPLETED, CancelledError, Executor, Future,
                                ThreadPoolExecutor, wait)
from dataclasses import dataclass
import logging
import threading
import time
from typing import TYPE_CHECKING, Callable
from uuid import uuid4

from app.models import Alert, Rule, RuleState, Track, TrackFrame, Verdict, Zone
from engine.alerts import attribute_alert, manual_review_alert, obstruction_alert, utc_now
from engine.crop import crop
from engine.zones import bbox_in_zone, validate_polygon
from verify.prompts import CHECK_FOR_ATTRIBUTE

if TYPE_CHECKING:
    import numpy as np

log = logging.getLogger('policylens.engine')

BUSY_REASON = 'verification busy'
BUSY_RETRY_SECONDS = 1.0
MAX_BUSY_RETRIES = 2
MAX_ALERT_FRAMES = 32
UNAVAILABLE = Verdict(answer=None, confidence=0, reason='verification unavailable')


def bbox_iou(a, b) -> float:
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1]))
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return intersection / (area_a + area_b - intersection)


def _default_verifier(image: 'np.ndarray | None', check: str) -> Verdict:
    """Import Person 2's verifier on first use, inside the worker thread."""
    from verify.verifier import verify_crop
    return verify_crop(image, check)


class InlineExecutor(Executor):
    """Runs each job inside submit(): deterministic replay and tests, no threads."""

    def submit(self, fn, /, *args, **kwargs) -> Future:
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:
            future.set_exception(exc)
        return future


@dataclass
class _Incident:
    id: str
    track: Track
    entered: float | None
    last_seen: float
    outside_since: float | None = None
    # timing -> alerted (persistent), or timing -> verifying -> alerted/compliant
    phase: str = 'timing'
    confidence_sum: float = 0
    observations: int = 0
    best_score: float = -1
    best_track: Track | None = None
    best_ts: float = 0
    best_frame: 'np.ndarray | None' = None

    def restart(self, entered: float | None) -> None:
        """Restart a pending timer; earlier observations no longer count."""
        self.entered = entered
        self.confidence_sum = 0
        self.observations = 0
        self.best_score = -1
        self.best_track = None
        self.best_frame = None


@dataclass
class _Job:
    rule: Rule
    incident: _Incident
    zone_name: str
    session_id: str
    crop: 'np.ndarray | None'
    check: str
    ticket: object = None
    threshold_ts: float = 0
    evidence_frames: object = None
    future: Future | None = None
    retries: int = 0
    retry_at: float = 0


class RuleEngine:
    """Persistent-object and attribute rules for one camera session.

    Each instance belongs to one camera session and is updated by one worker.
    Configuration is copied so editing a caller's models cannot mutate a live rule.
    Attribute verdicts arrive asynchronously; `update()` polls them and `drain()`
    waits for the rest.
    """

    def __init__(self, camera_id: str, zones: list[Zone], rules: list[Rule], *,
                 session_id: str | None = None,
                 clock: Callable[[], str] = utc_now,
                 verifier: Callable[['np.ndarray | None', str], Verdict] | None = None,
                 executor: Executor | None = None,
                 monotonic: Callable[[], float] = time.monotonic,
                 scheduler=None, evidence_writer=None):
        if not camera_id:
            raise ValueError('camera_id is required')
        if len({zone.id for zone in zones}) != len(zones):
            raise ValueError('Zone IDs must be unique')
        if len({rule.id for rule in rules}) != len(rules):
            raise ValueError('Rule IDs must be unique')
        if scheduler is not None and executor is not None:
            raise ValueError("Choose scheduler or executor")
        self.scheduler = scheduler
        self.evidence_writer = evidence_writer
        self._evidence_jobs = {}
        from engine.evidence import FrameBuffer
        self._buffer = FrameBuffer()
        self.camera_id = camera_id
        self.zones = {zone.id: zone.model_copy(deep=True) for zone in zones}
        self.rules = []
        for zone in zones:
            validate_polygon(zone.polygon)
        for rule in rules:
            if rule.zone not in self.zones:
                raise ValueError(f'Unknown zone: {rule.zone}')
            if not rule.enabled or self.zones[rule.zone].camera_id != camera_id:
                continue
            self.rules.append(rule.model_copy(deep=True))
        self.clock = clock
        self.verifier = verifier or _default_verifier
        self.monotonic = monotonic
        self.session_id = session_id or uuid4().hex
        self._executor = executor
        self._owns_executor = executor is None
        self._jobs: list[_Job] = []
        self._alert_frames: OrderedDict[str, 'np.ndarray'] = OrderedDict()
        self._alert_clips = OrderedDict()
        self._alert_frame_times = {}
        self._frames_lock = threading.Lock()
        self._incidents: dict[tuple[str, int], _Incident] = {}
        self._sequence = 0
        self._last_ts: float | None = None

    def reset(self) -> None:
        """Start a new session; old incident IDs can never collide with new ones.

        Pending verifications are abandoned, so their results never alert.
        """
        self._abandon_jobs()
        if self._buffer is not None:
            self._buffer.clear()
        self._incidents.clear()
        self._sequence = 0
        self._last_ts = None
        self.session_id = uuid4().hex

    def close(self) -> None:
        """Abandon pending verifications and shut down an engine-owned executor."""
        self._abandon_jobs()
        if self._owns_executor and self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    def pop_alert_frame(self, alert_id: str) -> 'np.ndarray | None':
        """Return and forget the frame an alert is about, or None without a frame.

        Persistent alerts keep the frame of the threshold update; attribute alerts
        keep the frame of the verified (best) observation.
        """
        with self._frames_lock:
            return self._alert_frames.pop(alert_id, None)

    def pop_alert_frame_ts(self, alert_id):
        with self._frames_lock:
            return self._alert_frame_times.pop(alert_id, None)

    def pop_alert_clip(self, alert_id):
        """Bounded source frames frozen when the alert first became due."""
        with self._frames_lock:
            return self._alert_clips.pop(alert_id, [])

    def drain(self, timeout: float = 10.0) -> list[Alert]:
        """Wait up to `timeout` wall seconds for pending verifications.

        Alerts use the last update's source timestamp. Jobs still pending at the
        deadline stay pending for a later update or drain.
        """
        deadline = time.monotonic() + timeout
        alerts = []
        while True:
            alerts.extend(self._poll(0.0 if self._last_ts is None else self._last_ts))
            remaining = deadline - time.monotonic()
            if not self._jobs or remaining <= 0:
                return alerts
            remaining = min(remaining, 0.02)
            running = [job.future for job in self._jobs if job.future is not None]
            if len(running) < len(self._jobs):  # some jobs wait to retry
                remaining = min(remaining, 0.05)
            if running:
                wait(running, timeout=remaining, return_when=FIRST_COMPLETED)
            else:
                time.sleep(remaining)

    def _abandon_jobs(self) -> None:
        if self.scheduler is not None:
            self.scheduler.cancel_session(self.camera_id, self.session_id)
        for job in self._jobs:
            if job.future is not None:
                job.future.cancel()
        self._jobs.clear()

    def _remember_frame(self, alert_id: str, frame, recent=None, snapshot_ts=None) -> None:
        if frame is None:
            return
        with self._frames_lock:
            self._alert_frames[alert_id] = frame
            self._alert_frame_times[alert_id] = self._last_ts if snapshot_ts is None else snapshot_ts
            self._alert_clips[alert_id] = self._buffer.snapshot(self._last_ts) if recent is None else recent
            while len(self._alert_clips) > MAX_ALERT_FRAMES:
                old_id, _ = self._alert_clips.popitem(last=False)
                self._alert_frame_times.pop(old_id, None)
            while len(self._alert_frames) > MAX_ALERT_FRAMES:
                old_id, _ = self._alert_frames.popitem(last=False)
                self._alert_clips.pop(old_id, None)
                self._alert_frame_times.pop(old_id, None)

    def _new_incident(self, rule: Rule, track: Track, ts: float) -> _Incident:
        self._sequence += 1
        return _Incident(
            id=f'{self.camera_id}:{self.session_id}:{rule.id}:{self._sequence}',
            track=track, entered=ts, last_seen=ts,
        )

    def _state(self, rule: Rule, incident: _Incident, ts: float, phase: str) -> RuleState:
        return RuleState(
            camera_id=self.camera_id, rule_id=rule.id,
            track_id=incident.track.track_id, incident_id=incident.id, ts=ts,
            elapsed_seconds=0 if incident.entered is None else ts - incident.entered,
            duration_seconds=rule.duration_seconds, phase=phase,
        )

    def _submit(self, job: _Job) -> None:
        if self.scheduler is not None:
            job.ticket = self.scheduler.submit(
                (self.camera_id, self.session_id, job.check, job.incident.id), job.crop, job.check)
            if job.ticket is None:
                job.future = Future()
                job.future.set_result(Verdict(answer=None, confidence=0, reason=BUSY_REASON))
            else:
                job.future = job.ticket.future
            return
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=4, thread_name_prefix=f'verify-{self.camera_id}')
        try:
            job.future = self._executor.submit(self.verifier, job.crop, job.check)
        except RuntimeError as exc:  # executor already shut down
            job.future = Future()
            job.future.set_exception(exc)

    def _start_verification(self, rule: Rule, incident: _Incident, zone_name: str) -> None:
        image = (None if incident.best_frame is None
                 else crop(incident.best_frame, incident.best_track.bbox))
        job = _Job(rule=rule, incident=incident, zone_name=zone_name,
                   session_id=self.session_id, crop=image,
                   check=CHECK_FOR_ATTRIBUTE[rule.attribute.name],
                   threshold_ts=self._last_ts,
                   evidence_frames=self._buffer.snapshot(self._last_ts) if self._buffer else [])
        self._submit(job)
        self._jobs.append(job)

    def _poll(self, ts: float) -> list[Alert]:
        """Resubmit busy jobs that are due and turn finished verdicts into alerts."""
        alerts = []
        now = self.monotonic()
        for job in list(self._jobs):
            if job.session_id != self.session_id:
                self._jobs.remove(job)
                continue
            if job.future is None:
                if now < job.retry_at:
                    continue
                self._submit(job)
            if job.ticket is not None:
                verdict = self.scheduler.poll(job.ticket)
                if verdict is None:
                    continue
            elif not job.future.done():
                continue
            try:
                if job.ticket is None:
                    verdict = Verdict.model_validate(job.future.result(), from_attributes=True)
            except (Exception, CancelledError):
                verdict = UNAVAILABLE
            if (verdict.answer is None and verdict.reason == BUSY_REASON
                    and job.retries < MAX_BUSY_RETRIES):
                job.retries += 1
                job.retry_at = now + BUSY_RETRY_SECONDS
                job.future = None
                job.ticket = None
                continue
            self._jobs.remove(job)
            alert = self._resolve(job, verdict, ts)
            if alert is not None:
                alerts.append(alert)
        return alerts

    def _resolve(self, job: _Job, verdict: Verdict, ts: float) -> Alert | None:
        incident, rule = job.incident, job.rule
        if self.scheduler is not None:
            ts = job.threshold_ts
        frame, incident.best_frame = incident.best_frame, None
        if verdict.answer is not None and verdict.answer == rule.attribute.expected:
            incident.phase = 'compliant'
            return None
        incident.phase = 'alerted'
        build = manual_review_alert if verdict.answer is None else attribute_alert
        alert = build(
            incident_id=incident.id, camera_id=self.camera_id, rule=rule,
            track=incident.best_track, ts=ts, elapsed=max(0, ts - incident.entered),
            verdict=verdict, zone_name=job.zone_name, created_at=self.clock(),
        )
        self._remember_frame(alert.id, frame, job.evidence_frames, incident.best_ts)
        self._capture_evidence(alert, frame, incident.best_ts, job.evidence_frames)
        return alert

    def update(self, frame, tf: TrackFrame) -> tuple[list[RuleState], list[Alert]]:
        """`frame` is the BGR image for `tf` (None in replay); it is never mutated.

        Empty frames are required for absence/closure accounting. Invalid camera
        or timestamp input raises before changing any incident state. Returned
        alerts include verdicts that finished since the previous update.
        """
        if tf.camera_id != self.camera_id:
            raise ValueError('Frame belongs to another camera')
        if self._last_ts is not None and tf.ts <= self._last_ts:
            raise ValueError('Timestamps must strictly increase; reset before rewind')
        self._last_ts = tf.ts
        if self._buffer is not None:
            self._buffer.remember(frame, tf.ts)
        states, alerts = [], self._poll(tf.ts)
        all_tracks = {track.track_id: track for track in tf.tracks}
        for rule in self.rules:
            zone = self.zones[rule.zone]
            attribute = rule.type == 'object_attribute'
            inside = {track.track_id: track for track in tf.tracks
                      if track.object_class in rule.objects
                      and bbox_in_zone(track.bbox, zone.polygon)}

            # Close expired incidents BEFORE matching/re-entry, including when a
            # sparse input jumps straight to a new observed frame.
            for key, incident in list(self._incidents.items()):
                if key[0] != rule.id:
                    continue
                absent_for = tf.ts - (incident.outside_since
                                     if incident.outside_since is not None
                                     else incident.last_seen)
                if absent_for >= 2.0 - 1e-9:
                    states.append(self._state(rule, incident, tf.ts, 'cleared'))
                    del self._incidents[key]
                elif key[1] in inside and inside[key[1]].object_class != incident.track.object_class:
                    states.append(self._state(rule, incident, tf.ts, 'cleared'))
                    del self._incidents[key]

            # Only recover an ID if both sides of the spatial match are unique.
            # A currently observed old ID is never eligible for recovery.
            candidates = {}
            for track_id, track in inside.items():
                if (rule.id, track_id) in self._incidents:
                    continue
                candidates[track_id] = [key for key, incident in self._incidents.items()
                    if key[0] == rule.id and key[1] not in all_tracks
                    and incident.outside_since is None
                    and tf.ts - incident.last_seen <= 1.0 + 1e-9
                    and track.object_class == incident.track.object_class
                    and bbox_iou(track.bbox, incident.track.bbox) >= 0.5]
            for track_id, keys in candidates.items():
                if len(keys) != 1:
                    continue
                key = keys[0]
                if sum(key in matches for matches in candidates.values()) != 1:
                    continue
                self._incidents[(rule.id, track_id)] = self._incidents.pop(key)

            for track_id, track in inside.items():
                key = (rule.id, track_id)
                incident = self._incidents.get(key)
                if incident is None:
                    incident = self._new_incident(rule, track, tf.ts)
                    self._incidents[key] = incident
                if incident.phase == 'timing' and (
                        incident.entered is None
                        or tf.ts - incident.last_seen > 1.0 + 1e-9):
                    incident.restart(tf.ts)
                incident.track = track
                incident.last_seen = tf.ts
                incident.outside_since = None
                incident.confidence_sum += track.confidence
                incident.observations += 1
                if attribute and incident.phase == 'timing':
                    x1, y1, x2, y2 = track.bbox
                    score = (x2 - x1) * (y2 - y1) * track.confidence
                    if score > incident.best_score:
                        incident.best_score = score
                        incident.best_track = track
                        incident.best_ts = tf.ts
                        incident.best_frame = None if frame is None else frame.copy()
                elapsed = tf.ts - incident.entered
                if incident.phase == 'timing' and elapsed >= rule.duration_seconds - 1e-9:
                    if attribute:
                        incident.phase = 'verifying'
                        self._start_verification(rule, incident, zone.name)
                    else:
                        incident.phase = 'alerted'
                        alert = obstruction_alert(
                            incident_id=incident.id, camera_id=self.camera_id, rule=rule,
                            track=track, ts=tf.ts, elapsed=elapsed,
                            confidence=incident.confidence_sum / incident.observations,
                            zone_name=zone.name, created_at=self.clock(),
                        )
                        self._remember_frame(alert.id, None if frame is None else frame.copy())
                        self._capture_evidence(alert, frame, tf.ts)
                        alerts.append(alert)
                states.append(self._state(rule, incident, tf.ts, incident.phase))

            for key, incident in self._incidents.items():
                if key[0] != rule.id or key[1] in inside:
                    continue
                if key[1] in all_tracks:
                    if incident.outside_since is None:
                        incident.outside_since = tf.ts
                    if incident.phase == 'timing':
                        incident.restart(None)
                elif (incident.outside_since is None
                      and tf.ts - incident.last_seen <= 1.0 + 1e-9):
                    states.append(self._state(rule, incident, tf.ts, incident.phase))
                elif incident.phase == 'timing':
                    incident.restart(None)
        return states, alerts

    def _capture_evidence(self, alert, image, snapshot_ts, frames=None):
        if self.evidence_writer is None:
            return
        if frames is None:
            frames = self._buffer.snapshot(alert.ts)
        try:
            ticket = self.evidence_writer.submit(alert, image, frames, snapshot_ts=snapshot_ts)
        except Exception:
            log.warning('Evidence submission failed camera=%s alert=%s', self.camera_id, alert.id)
            return
        if ticket is not None:
            alert.evidence_status = 'pending'
            self._evidence_jobs[alert.id] = ticket
        else:
            log.warning('Evidence queue full or image unavailable camera=%s alert=%s',
                        self.camera_id, alert.id)

    def poll_evidence(self):
        """Return completed evidence patches, not duplicate new alerts.

        The app should apply each patch to its latest stored alert and broadcast
        alert_updated. A shared writer cannot steal another camera's results.
        """
        results = []
        for alert_id, ticket in list(self._evidence_jobs.items()):
            result = self.evidence_writer.poll(ticket)
            if result is not None:
                results.append(result)
                del self._evidence_jobs[alert_id]
        return results

    def drain_evidence(self, timeout=10):
        """Blocking EOF/shutdown helper; live workers use poll_evidence instead."""
        deadline = time.monotonic() + timeout
        results = []
        while self._evidence_jobs:
            results.extend(self.poll_evidence())
            if not self._evidence_jobs:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError('Evidence drain timed out')
            time.sleep(0.002)
        return results

    def poll_verifications(self):
        return self._poll(self._last_ts or 0.0)

    def drain_verifications(self, timeout=5):
        return self.drain(timeout)

    def snapshot_states(self):
        return [self._state(rule, incident, self._last_ts or 0.0, incident.phase)
                for rule in self.rules for key, incident in self._incidents.items()
                if key[0] == rule.id]
