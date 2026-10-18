"""Deterministic safety net: validate, normalize and fill defaults, turning a DraftPolicy into
a CompileResult. Runs on every Gemini answer and on every fallback result."""

import re

from policy.contracts import SUPPORTED_ATTRIBUTES, Attribute, CompileResult, Rule, Zone
from policy.draft import DraftPolicy, DraftRule
from policy.synonyms import BAGS, GENERIC_UNSUPPORTED, classify_unsupported, default_severity, normalize_objects, zones_named_in

MIN_DURATION_S = 0.5
MAX_DURATION_S = 600.0
DEFAULT_ATTRIBUTE_DURATION_S = 1.0
DEFAULT_PERSISTENT_DURATION_S = 10.0
MAX_RULES = 10
MAX_UNSUPPORTED_CHARS = 300

# Default compliant value when the model leaves attribute_expected empty.
DEFAULT_EXPECTED = {"transparent": True, "professional": False}

_DURATION_NOTE = re.compile(r"\b(duration|time limit|how long)\b", re.IGNORECASE)
_BIG_CAMERA_WORDS = re.compile(r"\b(professional|pro|dslrs?|big|large|video|cinema|broadcast)\b", re.IGNORECASE)


def finalize(draft: DraftPolicy, zones: list[Zone]) -> CompileResult:
    warnings: list[str] = []
    rules: list[Rule] = []
    used_default_duration = False
    for draft_rule in draft.rules:
        rule, defaulted = _finalize_rule(draft_rule, zones, warnings)
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

    return CompileResult(rules=rules, warnings=_unique(warnings), unsupported=_clean_unsupported(draft.unsupported))


def _finalize_rule(d: DraftRule, zones: list[Zone], warnings: list[str]) -> tuple[Rule | None, bool]:
    source = _clean(d.source_text) or "this rule"
    quote = f"'{_shorten(source)}'"

    objects, dropped = normalize_objects(list(d.objects))
    if dropped:
        warnings.append(f"Ignored {', '.join(dropped)} in {quote}: I can only detect bags, chairs, people and cameras.")

    rule_type = d.type
    attribute = None
    if rule_type == "object_attribute":
        if d.attribute_name is None:
            if [o for o in objects if o != "person"]:
                rule_type = "persistent_object"
                warnings.append(f"Treated {quote} as a 'stays too long' rule because there's no attribute I can check.")
            else:
                warnings.append(f"I couldn't find anything I can check in {quote}, so I skipped it.")
                return None, False
        else:
            allowed = SUPPORTED_ATTRIBUTES[d.attribute_name]
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
        objects = [o for o in objects if o != "person"]
        if not objects:
            warnings.append(
                f"People can't be used in a 'stays too long' rule, because anyone walking through would alert. Skipped {quote}."
            )
            return None, False

    if not objects:
        warnings.append(f"I didn't find any object I can detect in {quote}, so I skipped it.")
        return None, False

    zone = _pick_zone(d.zone_id, source, quote, zones, warnings)
    if zone is None:
        return None, False

    defaulted = False
    duration = d.duration_seconds
    if duration is None:
        if rule_type == "persistent_object":
            duration = DEFAULT_PERSISTENT_DURATION_S
            defaulted = True
            warnings.append(f"No time limit given for {quote}; using {_fmt(duration)} seconds.")
        else:
            duration = DEFAULT_ATTRIBUTE_DURATION_S
    elif not MIN_DURATION_S <= duration <= MAX_DURATION_S:
        duration = min(max(duration, MIN_DURATION_S), MAX_DURATION_S)
        warnings.append(f"Adjusted the time in {quote} to {_fmt(duration)} seconds (the allowed range is 0.5 s to 10 minutes).")

    severity = d.severity or default_severity(source)

    rule = Rule(
        id="", name="", type=rule_type, objects=objects, zone=zone.id, attribute=attribute,
        duration_seconds=duration, severity=severity,
    )
    return rule, defaulted


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
    used: dict[str, int] = {}
    for rule in rules:
        base_id, name = _purpose(rule, zone_names.get(rule.zone, rule.zone))
        used[base_id] = used.get(base_id, 0) + 1
        rule.id = base_id if used[base_id] == 1 else f"{base_id}_{used[base_id]}"
        rule.name = name


def _purpose(rule: Rule, zone_name: str) -> tuple[str, str]:
    if rule.type == "object_attribute" and rule.attribute is not None:
        if rule.attribute.name == "transparent":
            return "clear_bag", "Clear-bag policy"
        return "pro_camera", "Camera policy"
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
