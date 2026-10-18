"""Build alerts from measured event facts, not generated explanations."""

from datetime import datetime, timezone

from app.models import Alert, Rule, Track


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def obstruction_alert(*, incident_id: str, camera_id: str, rule: Rule,
                      track: Track, ts: float, elapsed: float, confidence: float,
                      zone_name: str, created_at: str) -> Alert:
    article = 'An' if track.object_class[0].lower() in 'aeiou' else 'A'
    return Alert(
        id=f'{incident_id}:alert', incident_id=incident_id, camera_id=camera_id,
        rule_id=rule.id, rule_name=rule.name, zone_id=rule.zone,
        track_id=track.track_id, object_class=track.object_class, bbox=track.bbox,
        ts=ts, created_at=created_at, elapsed_seconds=elapsed,
        severity=rule.severity, title='Possible exit obstruction',
        observation=(f'{article} {track.object_class} was observed inside the '
                     f'{zone_name} zone for {elapsed:.1f} seconds, '
                     'allowing brief detection gaps.'),
        confidence=confidence, rule_snapshot=rule.model_copy(deep=True),
        evidence_status='unavailable',
    )
