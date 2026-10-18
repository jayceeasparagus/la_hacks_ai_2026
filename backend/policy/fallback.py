"""Deterministic, offline policy mapping for the demo prompt and close paraphrases.

Used when Gemini is down or returns garbage, and in FAKE mode. Its output goes through the
same capability checks as Gemini's.
"""

import logging
import re

from policy.contracts import Zone
from policy.draft import UNKNOWN_ZONE, DraftPolicy, DraftRule
from policy.synonyms import (
    BAGS, PERSON_DOWN, classify_unsupported, objects_in_text, parse_duration, zones_mentioned, zones_named_in,
)

log = logging.getLogger("policylens.policy")

_BAG_WORD = r"(?:bags?|backpacks?|purses?|totes?|handbags?)"
_BAG_MATERIAL = r"(?:(?:plastic|vinyl|pvc|stadium)\s+)?"
CLEAR_BAG = re.compile(
    rf"\b(?:clear|transparent|see-through)\s+{_BAG_MATERIAL}{_BAG_WORD}\b"
    rf"|\b{_BAG_WORD}\b[^.;]{{0,40}}\b(?:must|should|have to|has to|need to|needs to)\s+be\s+(?:clear|transparent|see-through)\b"
)
PRO_CAMERA = re.compile(r"\b(?:professional|pro|dslrs?|big|large)\b[^.;]{0,20}\bcameras?\b|\bdslrs?\b")
EXIT = re.compile(r"\b(?:exits?|fire (?:lanes?|doors?|exits?))\b")
# "clear" as in "keep it clear", not the "clear" of "clear bags".
KEEP_CLEAR = re.compile(rf"\b(?:clear(?!\s+{_BAG_MATERIAL}{_BAG_WORD}\b)|block\w*|obstruct\w*)\b")
# Words that only describe a person going down; "on the floor" alone could describe a bag.
PERSON_ONLY_DOWN = re.compile(r"\b(?:fallen|fell|collaps\w*|passed out|unconscious|(?:person|man|someone|somebody) down|(?:lying|laying) down)\b")
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
        mentioned = zones_mentioned(clause, zones)
        zone = named[0] if named else last_zone
        if named:
            last_zone = named[0]
        objects = objects_in_text(clause)
        things = [o for o in objects if o not in ("person", "camera")]
        found: list[DraftRule] = []

        if (PERSON_DOWN.search(low) and "person" in objects
                and (PERSON_ONLY_DOWN.search(low) or not things)):
            # capability.py turns this into a rule or an unsupported note, depending on the contracts.
            found.append(DraftRule(
                source_text=clause, type="persistent_object", objects=["person"],
                zone_id=zone.id if zone else UNKNOWN_ZONE, attribute_name="lying_down",
                attribute_expected=False, duration_seconds=parse_duration(clause), severity="urgent",
            ))
        # Admission rules apply to every zone the sentence names ("at the entrance and the exit").
        attribute_zones = mentioned or [zone]
        if CLEAR_BAG.search(low):
            found += [_attribute_rule(clause, BAGS, z, "transparent", True) for z in attribute_zones]
        if PRO_CAMERA.search(low):
            found += [_attribute_rule(clause, ["camera"], z, "professional", False) for z in attribute_zones]

        if EXIT.search(low) and KEEP_CLEAR.search(low):
            # Only people mentioned ("clear of people") -> keep them, so capability warns and drops the rule.
            exit_objects = things or (["person"] if "person" in objects and "clear of" in low else BAGS + ["chair"])
            found.append(DraftRule(
                source_text=clause, type="persistent_object", objects=exit_objects,
                zone_id=_exit_zone(named, zones), attribute_name=None, attribute_expected=None,
                duration_seconds=parse_duration(clause), severity="urgent",
            ))
        elif not found and LEFT_BEHIND.search(low) and things:
            found.append(DraftRule(
                source_text=clause, type="persistent_object", objects=things,
                zone_id=zone.id if zone else UNKNOWN_ZONE, attribute_name=None, attribute_expected=None,
                duration_seconds=parse_duration(clause), severity=None,
            ))

        rules += found
        # Zone names like "VIP lounge" or "Staff entrance" must not read as unsupported requests.
        sentence = classify_unsupported(_without_zone_names(clause, zones))
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


def _without_zone_names(text: str, zones: list[Zone]) -> str:
    for zone in zones:
        for name in (zone.name, zone.id.replace("_", " ")):
            text = re.sub(rf"\b{re.escape(name)}\b", " ", text, flags=re.IGNORECASE)
    return text


def _exit_zone(named: list[Zone], zones: list[Zone]) -> str:
    exit_like = [z for z in zones if re.search(r"exit|fire", f"{z.id} {z.name}".lower())]
    for zone in named:
        if zone in exit_like:
            return zone.id
    if exit_like:
        return exit_like[0].id
    return named[0].id if named else UNKNOWN_ZONE
