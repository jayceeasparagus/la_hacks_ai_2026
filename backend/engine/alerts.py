"""Build alerts from measured event facts, not generated explanations."""

from datetime import datetime, timezone

from app.models import Alert, Rule, Track, Verdict

# attribute -> (short title noun, phrase used in an observation sentence)
ATTRIBUTE_TERMS = {
    'transparent': ('clear bag', 'a clear bag'),
    'professional': ('professional camera', 'a professional-style camera'),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _article(word: str) -> str:
    return 'An' if word[0].lower() in 'aeiou' else 'A'


def _reason(verdict: Verdict) -> str:
    return verdict.reason.strip().rstrip('.') or 'no reason given'


def _alert(*, incident_id: str, camera_id: str, rule: Rule, track: Track, ts: float,
           elapsed: float, confidence: float, created_at: str, title: str,
           observation: str) -> Alert:
    return Alert(
        id=f'{incident_id}:alert', incident_id=incident_id, camera_id=camera_id,
        rule_id=rule.id, rule_name=rule.name, zone_id=rule.zone,
        track_id=track.track_id, object_class=track.object_class, bbox=track.bbox,
        ts=ts, created_at=created_at, elapsed_seconds=elapsed,
        severity=rule.severity, title=title, observation=observation,
        confidence=confidence, rule_snapshot=rule.model_copy(deep=True),
        evidence_status='unavailable',
    )


def obstruction_alert(*, incident_id: str, camera_id: str, rule: Rule,
                      track: Track, ts: float, elapsed: float, confidence: float,
                      zone_name: str, created_at: str) -> Alert:
    """A persistent object stayed in its zone; exit zones keep the demo wording."""
    is_exit = any('exit' in value.lower() for value in (rule.id, rule.zone, zone_name))
    return _alert(
        incident_id=incident_id, camera_id=camera_id, rule=rule, track=track, ts=ts,
        elapsed=elapsed, confidence=confidence, created_at=created_at,
        title='Possible exit obstruction' if is_exit else f'Possible {rule.name.lower()}',
        observation=(f'{_article(track.object_class)} {track.object_class} was observed '
                     f'inside the {zone_name} zone for {elapsed:.1f} seconds, '
                     'allowing brief detection gaps.'),
    )


def attribute_alert(*, incident_id: str, camera_id: str, rule: Rule, track: Track,
                    ts: float, elapsed: float, verdict: Verdict, zone_name: str,
                    created_at: str) -> Alert:
    """The verifier's answer differs from the attribute value the rule expects."""
    noun, phrase = ATTRIBUTE_TERMS[rule.attribute.name]
    looks = 'looks like' if verdict.answer else 'is probably not'
    return _alert(
        incident_id=incident_id, camera_id=camera_id, rule=rule, track=track, ts=ts,
        elapsed=elapsed, confidence=verdict.confidence, created_at=created_at,
        title=f'Possible {noun}' if verdict.answer else f'Possible non-{noun}',
        observation=(f'{_article(track.object_class)} {track.object_class} in the '
                     f'{zone_name} zone {looks} {phrase} (verifier: {_reason(verdict)}).'),
    )


def manual_review_alert(*, incident_id: str, camera_id: str, rule: Rule, track: Track,
                        ts: float, elapsed: float, verdict: Verdict, zone_name: str,
                        created_at: str) -> Alert:
    """The verifier could not tell; a person has to look, never a confirmed violation."""
    _, phrase = ATTRIBUTE_TERMS[rule.attribute.name]
    return _alert(
        incident_id=incident_id, camera_id=camera_id, rule=rule, track=track, ts=ts,
        elapsed=elapsed, confidence=verdict.confidence, created_at=created_at,
        title='Manual review needed',
        observation=(f"Couldn't tell whether the {track.object_class} in the {zone_name} "
                     f'zone is {phrase} ({_reason(verdict)}).'),
    )
