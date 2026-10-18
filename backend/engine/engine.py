"""Camera-local temporal rule engine. All timing uses source timestamps."""

from dataclasses import dataclass
from typing import Callable
from uuid import uuid4

from app.models import Alert, Rule, RuleState, Track, TrackFrame, Zone
from engine.alerts import obstruction_alert, utc_now
from engine.zones import bbox_in_zone, validate_polygon


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


class RuleEngine:
    """Persistent-object checkpoint; attribute rules are explicitly unavailable.

    Each instance belongs to one camera session and is updated by one worker.
    Configuration is copied so editing a caller's models cannot mutate a live rule.
    """

    def __init__(self, camera_id: str, zones: list[Zone], rules: list[Rule], *,
                 session_id: str | None = None,
                 clock: Callable[[], str] = utc_now):
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
            if rule.type != 'persistent_object':
                raise NotImplementedError('Attribute verification is the next increment')
            self.rules.append(rule.model_copy(deep=True))
        self.clock = clock
        self.session_id = session_id or uuid4().hex
        self._incidents: dict[tuple[str, int], _Incident] = {}
        self._sequence = 0
        self._last_ts: float | None = None

    def reset(self) -> None:
        """Start a new session; old incident IDs can never collide with new ones."""
        self._incidents.clear()
        self._sequence = 0
        self._last_ts = None
        self.session_id = uuid4().hex

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

            for track_id, track in inside.items():
                key = (rule.id, track_id)
                incident = self._incidents.get(key)
                if incident is None:
                    incident = self._new_incident(rule, track, tf.ts)
                    self._incidents[key] = incident
                if not incident.alerted and (
                        incident.entered is None
                        or tf.ts - incident.last_seen > 1.0 + 1e-9):
                    incident.entered = tf.ts
                    incident.confidence_sum = 0
                    incident.observations = 0
                incident.track = track
                incident.last_seen = tf.ts
                incident.outside_since = None
                incident.confidence_sum += track.confidence
                incident.observations += 1
                elapsed = tf.ts - incident.entered
                if not incident.alerted and elapsed >= rule.duration_seconds - 1e-9:
                    incident.alerted = True
                    alerts.append(obstruction_alert(
                        incident_id=incident.id, camera_id=self.camera_id, rule=rule,
                        track=track, ts=tf.ts, elapsed=elapsed,
                        confidence=incident.confidence_sum / incident.observations,
                        zone_name=zone.name, created_at=self.clock(),
                    ))
                states.append(self._state(rule, incident, tf.ts,
                                          'alerted' if incident.alerted else 'timing'))

            for key, incident in self._incidents.items():
                if key[0] != rule.id or key[1] in inside:
                    continue
                if key[1] in all_tracks:
                    if incident.outside_since is None:
                        incident.outside_since = tf.ts
                    if not incident.alerted:
                        incident.entered = None
                        incident.confidence_sum = 0
                        incident.observations = 0
                elif (incident.outside_since is None
                      and tf.ts - incident.last_seen <= 1.0 + 1e-9):
                    states.append(self._state(rule, incident, tf.ts,
                                              'alerted' if incident.alerted else 'timing'))
                elif not incident.alerted:
                    incident.entered = None
                    incident.confidence_sum = 0
                    incident.observations = 0
        return states, alerts
