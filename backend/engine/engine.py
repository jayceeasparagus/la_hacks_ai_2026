"""Camera-local temporal rule engine. All timing uses source timestamps."""

from dataclasses import dataclass
import logging
import time
from typing import TYPE_CHECKING, Callable
from uuid import uuid4

from app.models import Alert, Rule, RuleState, Track, TrackFrame, Zone
from engine.alerts import attribute_alert, obstruction_alert, utc_now
from engine.images import ImageSample, best_sample
from engine.verification import Ticket, VerificationScheduler, default_scheduler, unavailable
from engine.zones import bbox_in_zone, validate_polygon

if TYPE_CHECKING:
    from engine.evidence import EvidenceWriter

log = logging.getLogger('policylens.engine')


def bbox_iou(a, b) -> float:
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1]))
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return intersection / (area_a + area_b - intersection)


@dataclass
class _Incident:
    id: str
    track: Track
    entered: float | None
    last_seen: float
    outside_since: float | None = None
    alerted: bool = False
    confidence_sum: float = 0
    observations: int = 0
    original_track_id: int = 0
    phase: str = 'timing'
    best: ImageSample | None = None


@dataclass
class _Check:
    incident_id: str
    rule: Rule
    track: Track
    sample: ImageSample | None
    ts: float
    elapsed: float
    created_at: str
    ticket: Ticket | None
    evidence_frames: list


class RuleEngine:
    """Temporal rules and nonblocking visual-attribute verification.

    Each instance belongs to one camera session and is updated by one worker.
    Configuration is copied so editing a caller's models cannot mutate a live rule.
    """

    def __init__(self, camera_id: str, zones: list[Zone], rules: list[Rule], *,
                 session_id: str | None = None,
                 clock: Callable[[], str] = utc_now,
                 scheduler: VerificationScheduler | None = None,
                 evidence_writer: 'EvidenceWriter | None' = None):
        if not camera_id:
            raise ValueError('camera_id is required')
        if len({zone.id for zone in zones}) != len(zones):
            raise ValueError('Zone IDs must be unique')
        if len({rule.id for rule in rules}) != len(rules):
            raise ValueError('Rule IDs must be unique')
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
        self.session_id = session_id or uuid4().hex
        self._incidents: dict[tuple[str, int], _Incident] = {}
        self._sequence = 0
        self._last_ts: float | None = None
        self.scheduler = scheduler
        if any(rule.type == 'object_attribute' for rule in self.rules) and scheduler is None:
            self.scheduler = default_scheduler()
        self._checks: dict[str, _Check] = {}
        self._track_tickets: dict[tuple[str, int], Ticket] = {}
        self.evidence_writer = evidence_writer
        self._evidence_jobs = {}
        self._buffer = None
        if evidence_writer is not None:
            from engine.evidence import FrameBuffer
            self._buffer = FrameBuffer()

    def reset(self) -> None:
        """Start a new session; old incident IDs can never collide with new ones."""
        if self.scheduler is not None:
            self.scheduler.cancel_session(self.camera_id, self.session_id)
        self._checks.clear()
        self._track_tickets.clear()
        if self._buffer is not None:
            self._buffer.clear()
        # Already-created alerts retain their evidence jobs across a reconnect.
        # Each job owns its old-session snapshot and cannot mix in new frames.
        self._incidents.clear()
        self._sequence = 0
        self._last_ts = None
        self.session_id = uuid4().hex

    def _new_incident(self, rule: Rule, track: Track, ts: float) -> _Incident:
        self._sequence += 1
        return _Incident(
            id=f'{self.camera_id}:{self.session_id}:{rule.id}:{self._sequence}',
            track=track, entered=ts, last_seen=ts, original_track_id=track.track_id,
        )

    def _state(self, rule: Rule, incident: _Incident, ts: float, phase: str) -> RuleState:
        return RuleState(
            camera_id=self.camera_id, rule_id=rule.id,
            track_id=incident.track.track_id, incident_id=incident.id, ts=ts,
            elapsed_seconds=0 if incident.entered is None else ts - incident.entered,
            duration_seconds=rule.duration_seconds, phase=phase,
        )

    def update(self, frame, tf: TrackFrame) -> tuple[list[RuleState], list[Alert]]:
        """`frame` is reserved for the evidence/verification integration.

        Empty frames are required for absence/closure accounting. Invalid camera
        or timestamp input raises before changing any incident state.
        """
        if tf.camera_id != self.camera_id:
            raise ValueError('Frame belongs to another camera')
        if self._last_ts is not None and tf.ts <= self._last_ts:
            raise ValueError('Timestamps must strictly increase; reset before rewind')
        self._last_ts = tf.ts
        if self._buffer is not None:
            self._buffer.remember(frame, tf.ts)
        states, alerts = [], []
        all_tracks = {track.track_id: track for track in tf.tracks}
        for rule in self.rules:
            zone = self.zones[rule.zone]
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
                if incident.phase == 'timing' and not incident.alerted and (
                        incident.entered is None
                        or tf.ts - incident.last_seen > 1.0 + 1e-9):
                    incident.entered = tf.ts
                    incident.confidence_sum = 0
                    incident.observations = 0
                    incident.best = None
                incident.track = track
                incident.last_seen = tf.ts
                incident.outside_since = None
                incident.confidence_sum += track.confidence
                incident.observations += 1
                elapsed = tf.ts - incident.entered
                if rule.type == 'object_attribute':
                    if incident.phase == 'timing':
                        incident.best = best_sample(incident.best, frame, track, tf.ts)
                        if elapsed >= rule.duration_seconds - 1e-9:
                            self._submit_check(rule, incident, tf.ts, elapsed)
                elif not incident.alerted and elapsed >= rule.duration_seconds - 1e-9:
                    incident.alerted = True
                    incident.phase = 'alerted'
                    alert = obstruction_alert(
                        incident_id=incident.id, camera_id=self.camera_id, rule=rule,
                        track=track, ts=tf.ts, elapsed=elapsed,
                        confidence=incident.confidence_sum / incident.observations,
                        zone_name=zone.name, created_at=self.clock(),
                    )
                    self._capture_evidence(alert, frame, tf.ts)
                    alerts.append(alert)
                states.append(self._state(rule, incident, tf.ts, incident.phase))

            for key, incident in self._incidents.items():
                if key[0] != rule.id or key[1] in inside:
                    continue
                if key[1] in all_tracks:
                    if incident.outside_since is None:
                        incident.outside_since = tf.ts
                    if incident.phase == 'timing' and not incident.alerted:
                        incident.entered = None
                        incident.confidence_sum = 0
                        incident.observations = 0
                        incident.best = None
                elif (incident.outside_since is None
                      and tf.ts - incident.last_seen <= 1.0 + 1e-9):
                    states.append(self._state(rule, incident, tf.ts, incident.phase))
                elif incident.phase == 'timing' and not incident.alerted:
                    incident.entered = None
                    incident.confidence_sum = 0
                    incident.observations = 0
                    incident.best = None
        alerts.extend(self.poll_verifications())
        current = {incident.id: incident for incident in self._incidents.values()}
        for state in states:
            if state.phase != 'cleared' and state.incident_id in current:
                state.phase = current[state.incident_id].phase
        return states, alerts

    def _submit_check(self, rule: Rule, incident: _Incident, ts: float, elapsed: float):
        check = 'transparent_bag' if rule.attribute.name == 'transparent' else 'professional_camera'
        key = (check, incident.original_track_id)
        ticket = self._track_tickets.get(key)
        if incident.best is not None and ticket is None:
            try:
                ticket = self.scheduler.submit(
                    (self.camera_id, self.session_id, check, incident.original_track_id),
                    incident.best.crop, check)
            except RuntimeError:
                # A closed scheduler is handled as unavailable, not a frame-loop crash.
                ticket = None
                incident.best = None
            if ticket is None and incident.best is not None:
                return  # queue full: retry without blocking, retaining the best crop
            if ticket is not None:
                self._track_tickets[key] = ticket
        incident.phase = 'verifying'
        self._checks[incident.id] = _Check(
            incident.id, rule, (incident.best.track if incident.best else incident.track),
            incident.best, ts, elapsed, self.clock(), ticket,
            self._buffer.snapshot(ts) if self._buffer is not None else [])

    def poll_verifications(self) -> list[Alert]:
        """Collect results even when video is paused; does not advance source time."""
        alerts = []
        for incident_id, check in list(self._checks.items()):
            verdict = (self.scheduler.poll(check.ticket) if check.ticket is not None
                       else unavailable('no usable crop or verification worker unavailable'))
            if verdict is None:
                continue
            del self._checks[incident_id]
            active = next((incident for incident in self._incidents.values()
                           if incident.id == incident_id), None)
            violation = verdict.answer is None or verdict.answer != check.rule.attribute.expected
            if active is not None:
                active.phase = 'alerted' if violation else 'compliant'
                active.alerted = violation
                active.best = None
            if violation:
                alert = attribute_alert(
                    incident_id=incident_id, camera_id=self.camera_id, rule=check.rule,
                    track=check.track, verdict=verdict, ts=check.ts, elapsed=check.elapsed,
                    created_at=check.created_at)
                sample = check.sample
                self._capture_evidence(alert, sample.image if sample else None,
                    sample.ts if sample else check.ts, check.evidence_frames)
                alerts.append(alert)
        return alerts

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

    def drain_verifications(self, timeout=5) -> list[Alert]:
        """Blocking replay/shutdown helper; never call from a live frame loop."""
        deadline = time.monotonic() + timeout
        alerts = []
        while self._checks:
            alerts.extend(self.poll_verifications())
            if not self._checks:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError('Verification drain timed out')
            time.sleep(0.002)
        return alerts
