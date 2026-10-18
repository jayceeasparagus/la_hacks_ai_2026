"""Build alerts from measured event facts, not generated explanations."""

from datetime import datetime, timezone

from app.models import Alert, Rule, Track, Verdict

# attribute -> (short title noun, phrase used in an observation sentence)
ATTRIBUTE_TERMS = {
    'transparent': ('clear bag', 'a clear bag'),
    'professional': ('professional camera', 'a professional-style camera'),
    'hard_hat': ('hard hat', 'wearing a hard hat'),
    'safety_vest': ('safety vest', 'wearing a safety vest'),
    'jeans': ('jeans', 'wearing jeans'),
}
# Safety gear a person should wear: a violation means the gear is probably missing.
WEARABLE = {'hard_hat', 'safety_vest', 'jeans'}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _article(word: str) -> str:
    return 'An' if word[0].lower() in 'aeiou' else 'A'


def _in_zone(zone_name: str | None) -> str:
    """' in the X zone', or nothing when the zone is the whole frame (zone_name None)."""
    return f' in the {zone_name} zone' if zone_name else ''


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


def is_prohibition(rule: Rule) -> bool:
    # The compiler marks "No bags" style rules with ids like no_bags, no_chairs, no_bags_2.
    return rule.id.startswith('no_')


def obstruction_alert(*, incident_id: str, camera_id: str, rule: Rule,
                      track: Track, ts: float, elapsed: float, confidence: float,
                      zone_name: str | None, created_at: str) -> Alert:
    """A persistent object stayed in its zone; exit zones keep the demo wording."""
    if is_prohibition(rule):
        title = f'Possible {track.object_class} in view'
    elif any('exit' in value.lower() for value in (rule.id, rule.zone, zone_name or '')):
        title = 'Possible exit obstruction'
    else:
        title = f'Possible {rule.name.lower()}'
    return _alert(
        incident_id=incident_id, camera_id=camera_id, rule=rule, track=track, ts=ts,
        elapsed=elapsed, confidence=confidence, created_at=created_at,
        title=title,
        observation=(f'{_article(track.object_class)} {track.object_class} was observed'
                     f'{f" inside the {zone_name} zone" if zone_name else " in view"} for {elapsed:.1f} seconds, '
                     'allowing brief detection gaps.'),
    )


def attribute_alert(*, incident_id: str, camera_id: str, rule: Rule, track: Track,
                    ts: float, elapsed: float, verdict: Verdict, zone_name: str | None,
                    created_at: str) -> Alert:
    """The verifier's answer differs from the attribute value the rule expects."""
    noun, phrase = ATTRIBUTE_TERMS[rule.attribute.name]
    looks = 'looks like' if verdict.answer else 'is probably not'
    if rule.attribute.name in WEARABLE:
        looks = 'is probably' if verdict.answer else 'is probably not'  # "is probably wearing jeans"
        title = f'Possible {noun} worn' if verdict.answer else f'Possible missing {noun}'
    else:
        title = f'Possible {noun}' if verdict.answer else f'Possible non-{noun}'
    return _alert(
        incident_id=incident_id, camera_id=camera_id, rule=rule, track=track, ts=ts,
        elapsed=elapsed, confidence=verdict.confidence, created_at=created_at,
        title=title,
        observation=(f'{_article(track.object_class)} {track.object_class}{_in_zone(zone_name)} '
                     f'{looks} {phrase} (verifier: {_reason(verdict)}).'),
    )


def manual_review_alert(*, incident_id: str, camera_id: str, rule: Rule, track: Track,
                        ts: float, elapsed: float, verdict: Verdict, zone_name: str | None,
                        created_at: str) -> Alert:
    """The verifier could not tell; a person has to look, never a confirmed violation."""
    _, phrase = ATTRIBUTE_TERMS[rule.attribute.name]
    return _alert(
        incident_id=incident_id, camera_id=camera_id, rule=rule, track=track, ts=ts,
        elapsed=elapsed, confidence=verdict.confidence, created_at=created_at,
        title='Manual review needed',
        observation=(f"Couldn't tell whether the {track.object_class}{_in_zone(zone_name)} "
                     f'is {phrase} ({_reason(verdict)}).'),
    )
