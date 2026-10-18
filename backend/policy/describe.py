"""Plain-English rule conditions for the review screen, written from the rule fields."""

from policy.contracts import Rule, Zone
from policy.synonyms import BAGS


def describe_rule(rule: Rule, zones: list[Zone]) -> str:
    """For example "Bag is probably opaque" or "Bag or chair stays for 5 seconds".

    `zones` is accepted for future wording that names the zone; the condition text does not use it yet.
    """
    noun = _noun_phrase(rule.objects)
    seconds = rule.duration_seconds
    amount = str(int(seconds)) if float(seconds).is_integer() else f"{seconds:g}"
    unit = "second" if seconds == 1 else "seconds"
    if rule.attribute is not None and rule.attribute.name == "lying_down":
        return f"Person probably down for {amount} {unit}"
    if rule.type == "object_attribute" and rule.attribute is not None:
        if rule.attribute.name == "transparent":
            return f"{noun} is probably {'opaque' if rule.attribute.expected else 'transparent'}"
        if rule.attribute.expected:
            return "Camera is probably not professional-style"
        return "Professional-style camera detected"
    return f"{noun} stays for {amount} {unit}"


def _noun_phrase(objects: list[str]) -> str:
    words: list[str] = []
    for obj in objects:
        word = "bag" if obj in BAGS else obj
        if word not in words:
            words.append(word)
    phrase = " or ".join(words) if words else "object"
    return phrase[0].upper() + phrase[1:]
