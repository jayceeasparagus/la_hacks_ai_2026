"""Deterministic safety net: validate, normalize and fill defaults, turning a DraftPolicy into
a CompileResult. Runs on every Gemini answer and on every fallback result."""

import math
import re

from policy.contracts import Attribute, CompileResult, Rule, Zone
from policy.draft import DraftPolicy, DraftRule
from policy.synonyms import (
    BAGS, GENERIC_UNSUPPORTED, PERSISTENT_OBJECTS, PERSON_DOWN, PERSON_DOWN_UNSUPPORTED, classify_unsupported,
    default_severity, normalize_objects, objects_with_attribute, person_down_enabled, zones_named_in,
)

MIN_DURATION_S = 0.5
MAX_DURATION_S = 600.0
DEFAULT_ATTRIBUTE_DURATION_S = 1.0
DEFAULT_PERSISTENT_DURATION_S = 10.0
MAX_RULES = 10
MAX_UNSUPPORTED_CHARS = 300

# Default compliant value when the model leaves attribute_expected empty.
DEFAULT_EXPECTED = {"transparent": True, "professional": False, "hard_hat": True, "safety_vest": True}

# (id, name) for object_attribute rules, by attribute.
ATTRIBUTE_PURPOSES = {
    "transparent": ("clear_bag", "Clear-bag policy"),
    "professional": ("pro_camera", "Camera policy"),
    "hard_hat": ("hard_hat", "Hard-hat policy"),
    "safety_vest": ("safety_vest", "Safety-vest policy"),
}

_DURATION_NOTE = re.compile(r"\b(duration|time limit|how long)\b", re.IGNORECASE)
_BIG_CAMERA_WORDS = re.compile(r"\b(professional|pro|dslrs?|big|large|video|cinema|broadcast)\b", re.IGNORECASE)


def finalize(draft: DraftPolicy, zones: list[Zone]) -> CompileResult:
    warnings: list[str] = []
    unsupported: list[str] = list(draft.unsupported)
    rules: list[Rule] = []
    used_default_duration = False
    for draft_rule in draft.rules:
        rule, defaulted = _finalize_rule(draft_rule, zones, warnings, unsupported)
        used_default_duration |= defaulted
        if rule is not None:
            rules.append(rule)

    rules = _merge_duplicates(rules)
    if len(rules) > MAX_RULES:
        warnings.append(f"That's more than {MAX_RULES} rules; I kept the first {MAX_RULES}.")
        rules = rules[:MAX_RULES]
    _assign_ids_and_names(rules, zones)

    for note in draft.ambiguities:
        note = _clean(note)
        # My own default-duration warning is more specific than the model's note.
        if note and not (used_default_duration and _DURATION_NOTE.search(note)):
            warnings.append(note)

    return CompileResult(rules=rules, warnings=_unique(warnings), unsupported=_clean_unsupported(unsupported))


def _finalize_rule(d: DraftRule, zones: list[Zone], warnings: list[str],
                   unsupported: list[str]) -> tuple[Rule | None, bool]:
    source = _clean(d.source_text) or "this rule"
    quote = f"'{_shorten(source)}'"

    objects, dropped = normalize_objects(list(d.objects))
    if dropped:
        warnings.append(f"Ignored {', '.join(dropped)} in {quote}: I can only detect bags, chairs, people and cameras.")

    if d.attribute_name == "lying_down" or ("person" in objects and PERSON_DOWN.search(source.lower())):
        return _person_down_rule(d, source, quote, zones, warnings, unsupported)

    rule_type = d.type
    attribute = None
    if rule_type == "object_attribute":
        if d.attribute_name is None:
            if [o for o in objects if o in PERSISTENT_OBJECTS]:
                rule_type = "persistent_object"
                warnings.append(f"Treated {quote} as a 'stays too long' rule because there's no attribute I can check.")
            else:
                warnings.append(f"I couldn't find anything I can check in {quote}, so I skipped it.")
                return None, False
        else:
            allowed = objects_with_attribute(d.attribute_name)
            if not allowed:
                warnings.append(f"I can't check '{d.attribute_name}' yet, so I skipped {quote}.")
                return None, False
            bad = [o for o in objects if o not in allowed]
            objects = [o for o in objects if o in allowed]
            if not objects:
                warnings.append(f"I can only check '{d.attribute_name}' on {', '.join(allowed)}, so I skipped {quote}.")
                return None, False
            if bad:
                warnings.append(f"Removed {', '.join(bad)} from {quote}: '{d.attribute_name}' only applies to {', '.join(allowed)}.")
            expected = d.attribute_expected
            if expected is None:
                expected = DEFAULT_EXPECTED[d.attribute_name]
            attribute = Attribute(name=d.attribute_name, expected=expected)
            if d.attribute_name == "professional" and not _BIG_CAMERA_WORDS.search(source):
                warnings.append(f"I can only spot larger, professional-style cameras; phones and small cameras won't trigger {quote}.")

    if rule_type == "persistent_object":
        had_people = "person" in objects
        others = [o for o in objects if o not in PERSISTENT_OBJECTS and o != "person"]
        objects = [o for o in objects if o in PERSISTENT_OBJECTS]
        if others and objects:
            warnings.append(f"Removed {', '.join(others)} from {quote}: 'stays too long' rules only watch bags and chairs.")
        if not objects:
            if had_people:
                warnings.append(
                    f"People can't be used in a 'stays too long' rule, because anyone walking through would alert. Skipped {quote}."
                )
            else:
                warnings.append(f"'Stays too long' rules only watch bags and chairs, so I skipped {quote}.")
            return None, False

    if not objects:
        warnings.append(f"I didn't find any object I can detect in {quote}, so I skipped it.")
        return None, False

    zone = _pick_zone(d.zone_id, source, quote, zones, warnings)
    if zone is None:
        return None, False

    duration, defaulted = _duration(d.duration_seconds, rule_type, quote, warnings)
    severity = d.severity or default_severity(source)

    # id and name are filled in by _assign_ids_and_names once all rules are known.
    rule = Rule(
        id="pending", name="pending", type=rule_type, objects=objects, zone=zone.id, attribute=attribute,
        duration_seconds=duration, severity=severity,
    )
    return rule, defaulted


def _person_down_rule(d: DraftRule, source: str, quote: str, zones: list[Zone], warnings: list[str],
                      unsupported: list[str]) -> tuple[Rule | None, bool]:
    """Stretch goal: a persistent rule on people whose crop is verified as lying down.
    Only produced once the contracts support lying_down; until then it is reported as unsupported."""
    if not person_down_enabled():
        unsupported.append(PERSON_DOWN_UNSUPPORTED)
        return None, False
    zone = _pick_zone(d.zone_id, source, quote, zones, warnings)
    if zone is None:
        return None, False
    duration, defaulted = _duration(d.duration_seconds, "persistent_object", quote, warnings)
    rule = Rule(
        id="pending", name="pending", type="persistent_object", objects=["person"], zone=zone.id,
        attribute=Attribute(name="lying_down", expected=False), duration_seconds=duration,
        severity=d.severity or "urgent",
    )
    return rule, defaulted


def _duration(seconds: float | None, rule_type: str, quote: str, warnings: list[str]) -> tuple[float, bool]:
    """(duration, whether the default was used): defaults, clamping and the matching warnings."""
    if seconds is not None and math.isnan(seconds):  # Pydantic accepts a bare NaN in JSON
        seconds = None
    if seconds is None:
        if rule_type == "object_attribute":
            return DEFAULT_ATTRIBUTE_DURATION_S, False
        warnings.append(f"No time limit given for {quote}; using {_fmt(DEFAULT_PERSISTENT_DURATION_S)} seconds.")
        return DEFAULT_PERSISTENT_DURATION_S, True
    if not MIN_DURATION_S <= seconds <= MAX_DURATION_S:
        seconds = min(max(seconds, MIN_DURATION_S), MAX_DURATION_S)
        warnings.append(f"Adjusted the time in {quote} to {_fmt(seconds)} seconds (the allowed range is 0.5 s to 10 minutes).")
    return seconds, False


def _pick_zone(zone_id: str, source: str, quote: str, zones: list[Zone], warnings: list[str]) -> Zone | None:
    by_id = {z.id: z for z in zones}
    zone = by_id.get(zone_id)
    if zone is None:
        if len(zones) == 1:
            zone = zones[0]
            warnings.append(f"Applied {quote} to {zone.name} because it's the only zone.")
        else:
            warnings.append(f"Which zone should {quote} apply to? Draw or name a zone and compile again.")
            return None

    named = zones_named_in(source, zones)
    cameras = sorted({z.camera_id for z in named})
    if zone in named and len(cameras) > 1:
        warnings.append(
            f"{quote} matches zones on more than one camera ({', '.join(cameras)}); I used {zone.name} on "
            f"{zone.camera_id}. Rename a zone if that's wrong."
        )
    return zone


def _merge_duplicates(rules: list[Rule]) -> list[Rule]:
    seen = set()
    merged = []
    for rule in rules:
        key = rule.model_dump_json(exclude={"id", "name"})
        if key not in seen:
            seen.add(key)
            merged.append(rule)
    return merged


def _assign_ids_and_names(rules: list[Rule], zones: list[Zone]) -> None:
    zone_names = {z.id: z.name for z in zones}
    used: set[str] = set()
    for rule in rules:
        base_id, name = _purpose(rule, zone_names.get(rule.zone, rule.zone))
        rule_id, n = base_id, 1
        while rule_id in used:  # the engine keys incidents by rule id, so ids must be unique
            n += 1
            rule_id = f"{base_id}_{n}"
        used.add(rule_id)
        rule.id = rule_id
        rule.name = name


def _purpose(rule: Rule, zone_name: str) -> tuple[str, str]:
    if rule.attribute is not None and rule.attribute.name == "lying_down":
        return "person_down", "Possible person down"
    if rule.type == "object_attribute" and rule.attribute is not None:
        return ATTRIBUTE_PURPOSES[rule.attribute.name]
    if "exit" in f"{rule.zone} {zone_name}".lower():
        return "blocked_exit", "Exit obstruction"
    if rule.severity == "urgent":
        return f"blocked_{_slug(rule.zone)}", f"{zone_name} obstruction"
    noun = _object_noun(rule.objects)
    return f"unattended_{noun}", f"Unattended {noun}"


def _object_noun(objects: list[str]) -> str:
    if all(o in BAGS for o in objects):
        return "bag"
    if len(objects) == 1:
        return objects[0]
    return "object"


def _clean_unsupported(items: list[str]) -> list[str]:
    cleaned = []
    for item in items:
        text = _clean(item).replace("’", "'")
        if not text:
            continue
        if not text.lower().startswith(("i can't", "i cannot")):
            text = classify_unsupported(text) or GENERIC_UNSUPPORTED
        if len(text) > MAX_UNSUPPORTED_CHARS:
            text = text[:MAX_UNSUPPORTED_CHARS].rsplit(" ", 1)[0].rstrip(",;") + "."
        cleaned.append(text)
    return _unique(cleaned)


def _clean(text: str) -> str:
    return " ".join((text or "").split())


def _shorten(text: str, limit: int = 60) -> str:
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "..."


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _fmt(seconds: float) -> str:
    return str(int(seconds)) if float(seconds).is_integer() else f"{seconds:g}"


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))
