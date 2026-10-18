"""Deterministic, offline policy mapping for the demo prompt and close paraphrases.

Used when Gemini is down or returns garbage, and in FAKE mode. Its output goes through the
same capability checks as Gemini's.
"""

import logging
import re

from policy.contracts import Zone
from policy.draft import UNKNOWN_ZONE, DraftPolicy, DraftRule
from policy.synonyms import BAGS, classify_unsupported, objects_in_text, parse_duration, zones_named_in

log = logging.getLogger("policylens.policy")

_BAG_WORD = r"(?:bags?|backpacks?|purses?|totes?|handbags?)"
CLEAR_BAG = re.compile(
    rf"\b(?:clear|transparent|see-through)\s+(?:\w+\s+)?{_BAG_WORD}\b"
    rf"|\b{_BAG_WORD}\b[^.;]{{0,40}}\b(?:must|should|have to|has to|need to|needs to)\s+be\s+(?:clear|transparent|see-through)\b"
)
PRO_CAMERA = re.compile(r"\b(?:professional|pro|dslrs?|big|large)\b[^.;]{0,20}\bcameras?\b|\bdslrs?\b")
EXIT = re.compile(r"\b(?:exits?|fire (?:lanes?|doors?|exits?))\b")
KEEP_CLEAR = re.compile(r"\b(?:clear|block\w*|obstruct\w*)\b")
LEFT_BEHIND = re.compile(r"\b(?:leav\w*|left|unattended|abandon\w*|sit\w*|stay\w*|remain\w*|block\w*|park\w*)\b")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")


def compile_fallback(prompt: str, zones: list[Zone]) -> DraftPolicy | None:
    """A DraftPolicy for prompts we recognize, or None."""
    rules: list[DraftRule] = []
    unsupported: list[str] = []
    last_zone: Zone | None = None

    for clause in (c.strip() for c in _SENTENCE_END.split(prompt)):
        if not clause:
            continue
        low = clause.lower()
        named = zones_named_in(clause, zones)
        zone = named[0] if named else last_zone
        if named:
            last_zone = named[0]
        found: list[DraftRule] = []

        if CLEAR_BAG.search(low):
            found.append(_attribute_rule(clause, BAGS, zone, "transparent", True))
        if PRO_CAMERA.search(low):
            found.append(_attribute_rule(clause, ["camera"], zone, "professional", False))

        if EXIT.search(low) and KEEP_CLEAR.search(low):
            objects = [o for o in objects_in_text(clause) if o not in ("person", "camera")] or BAGS + ["chair"]
            found.append(DraftRule(
                source_text=clause, type="persistent_object", objects=objects,
                zone_id=_exit_zone(named, zones), attribute_name=None, attribute_expected=None,
                duration_seconds=parse_duration(clause), severity="urgent",
            ))
        elif not found and LEFT_BEHIND.search(low):
            objects = [o for o in objects_in_text(clause) if o not in ("person", "camera")]
            if objects:
                found.append(DraftRule(
                    source_text=clause, type="persistent_object", objects=objects,
                    zone_id=named[0].id if named else UNKNOWN_ZONE, attribute_name=None, attribute_expected=None,
                    duration_seconds=parse_duration(clause), severity=None,
                ))

        rules += found
        sentence = classify_unsupported(clause)
        if sentence and sentence not in unsupported:
            unsupported.append(sentence)

    if not rules and not unsupported:
        return None
    return DraftPolicy(rules=rules, unsupported=unsupported, ambiguities=[])


def _attribute_rule(clause: str, objects: list[str], zone: Zone | None, attribute: str, expected: bool) -> DraftRule:
    return DraftRule(
        source_text=clause, type="object_attribute", objects=objects,
        zone_id=zone.id if zone else UNKNOWN_ZONE, attribute_name=attribute, attribute_expected=expected,
        duration_seconds=None, severity="review",
    )


def _exit_zone(named: list[Zone], zones: list[Zone]) -> str:
    exit_like = [z for z in zones if re.search(r"exit|fire", f"{z.id} {z.name}".lower())]
    for zone in named:
        if zone in exit_like:
            return zone.id
    if exit_like:
        return exit_like[0].id
    return named[0].id if named else UNKNOWN_ZONE
