"""Word mappings: objects, durations, severity hints, zone names and unsupported topics."""

import re

from policy.contracts import SUPPORTED_ATTRIBUTES, SUPPORTED_OBJECTS, Zone

BAGS = ["backpack", "handbag", "suitcase"]

OBJECT_SYNONYMS = {
    "bag": BAGS, "bags": BAGS,
    "backpack": ["backpack"], "backpacks": ["backpack"],
    "handbag": ["handbag"], "handbags": ["handbag"],
    "purse": ["handbag"], "purses": ["handbag"], "tote": ["handbag"], "totes": ["handbag"],
    "suitcase": ["suitcase"], "suitcases": ["suitcase"], "luggage": ["suitcase"],
    "chair": ["chair"], "chairs": ["chair"], "seat": ["chair"], "seats": ["chair"],
    "stool": ["chair"], "stools": ["chair"],
    "camera": ["camera"], "cameras": ["camera"], "dslr": ["camera"], "dslrs": ["camera"],
    "person": ["person"], "persons": ["person"], "people": ["person"],
    "someone": ["person"], "somebody": ["person"], "anyone": ["person"], "anybody": ["person"],
}


def normalize_objects(words: list[str]) -> tuple[list[str], list[str]]:
    """Map words to supported objects. Returns (objects, dropped words), de-duplicated in order."""
    objects: list[str] = []
    dropped: list[str] = []
    for word in words:
        key = word.strip().lower()
        mapped = [key] if key in SUPPORTED_OBJECTS else OBJECT_SYNONYMS.get(key)
        if mapped is None:
            dropped.append(word)
            continue
        objects += [o for o in mapped if o not in objects]
    return objects, dropped


def objects_in_text(text: str) -> list[str]:
    words = [w for w in re.findall(r"[a-z]+", text.lower()) if w in OBJECT_SYNONYMS]
    return normalize_objects(words)[0]


# --- durations --------------------------------------------------------------------------

NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
    "thirty": 30, "forty": 40, "forty-five": 45, "fifty": 50, "sixty": 60, "ninety": 90,
}
_UNIT_SECONDS = {"s": 1, "sec": 1, "second": 1, "m": 60, "min": 60, "minute": 60, "h": 3600, "hr": 3600, "hour": 3600}
_DIGIT_DURATION = re.compile(r"(\d+(?:\.\d+)?)[\s-]*(seconds?|secs?|s|minutes?|mins?|hours?|hrs?|h)\b")
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_UNITS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
_WORD_DURATION = re.compile(
    r"\b((?:" + "|".join(_TENS) + r")[\s-](?:" + "|".join(_UNITS) + r")"  # "twenty-five", "thirty five"
    r"|" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")[\s-]+(seconds?|minutes?|hours?)\b"
)


def _word_number(words: str) -> float:
    parts = re.split(r"[\s-]", words)
    if len(parts) == 2 and parts[0] in _TENS:
        return _TENS[parts[0]] + _UNITS[parts[1]]
    return NUMBER_WORDS[words]
_HALF = re.compile(r"\bhalf (?:a|an) (minute|hour)\b")


def parse_duration(text: str) -> float | None:
    """First duration in the text, in seconds ("five seconds" -> 5, "half a minute" -> 30)."""
    low = text.lower()
    found: list[tuple[int, float]] = []
    if m := _HALF.search(low):
        found.append((m.start(), 0.5 * _unit(m.group(1))))
    if m := _DIGIT_DURATION.search(low):
        found.append((m.start(), float(m.group(1)) * _unit(m.group(2))))
    if m := _WORD_DURATION.search(low):
        found.append((m.start(), _word_number(m.group(1)) * _unit(m.group(2))))
    return min(found)[1] if found else None


def _unit(word: str) -> int:
    word = word.rstrip("s") or "s"
    return _UNIT_SECONDS.get(word, _UNIT_SECONDS.get(word[:3], 1))


# --- severity ---------------------------------------------------------------------------

URGENT_HINTS = re.compile(r"\b(exits?|fire|block\w*|obstruct\w*|safety|emergenc\w*|immediately|urgent\w*)\b")


def default_severity(text: str) -> str:
    return "urgent" if URGENT_HINTS.search(text.lower()) else "review"


# --- zones ------------------------------------------------------------------------------

_GENERIC_ZONE_WORDS = {"the", "and", "zone", "area", "main", "side", "camera", "cam"}


def zones_named_in(text: str, zones: list[Zone]) -> list[Zone]:
    """The best-matching zones the text mentions (several only on a tie, in zone order)."""
    scored = _zone_scores(text, zones)
    return [z for score, z in scored if score == scored[0][0]] if scored else []


def zones_mentioned(text: str, zones: list[Zone]) -> list[Zone]:
    """Every zone the text mentions by its full name, in zone order."""
    low = text.lower()
    return [z for z in zones if re.search(rf"\b{re.escape(z.name.lower())}\b", low)]


def _zone_scores(text: str, zones: list[Zone]) -> list[tuple[int, Zone]]:
    low = text.lower()
    words = set(re.findall(r"[a-z0-9]+", low))
    scored = []
    for index, zone in enumerate(zones):
        tokens = {t for t in re.findall(r"[a-z0-9]+", f"{zone.name} {zone.id}".lower())
                  if (len(t) >= 3 or t.isdigit()) and t not in _GENERIC_ZONE_WORDS}
        score = sum(1 for t in tokens if t in words or t + "s" in words or (t.endswith("s") and t[:-1] in words))
        if re.search(rf"\b{re.escape(zone.name.lower())}\b", low):
            score += 2
        if score:
            scored.append((-score, index, zone))
    return [(-s, z) for s, _, z in sorted(scored, key=lambda x: (x[0], x[1]))]


# --- person down (stretch goal, needs the lying_down attribute in the contracts) -------------

PERSON_DOWN = re.compile(
    r"\b(?:on the (?:floor|ground)|(?:lying|laying) (?:down|on)|fallen|fell|collaps\w*|passed out|unconscious"
    r"|(?:person|man|someone|somebody) down)\b"
)
PERSON_DOWN_UNSUPPORTED = (
    "I can't check whether someone is lying on the floor yet. I can monitor bags, chairs and large cameras "
    "in the zones you've drawn."
)


def person_down_enabled() -> bool:
    """True once the shared contracts support the lying_down attribute on person."""
    return "person" in SUPPORTED_ATTRIBUTES.get("lying_down", [])


# --- unsupported requests ---------------------------------------------------------------

GENERIC_UNSUPPORTED = (
    "I can't monitor that with these cameras. I can watch for bags, chairs, people and large cameras "
    "in the zones you've drawn."
)

# Checked in order; the first match wins.
UNSUPPORTED_TOPICS: list[tuple[str, re.Pattern, str]] = [
    ("injection",
     re.compile(r"\bignore (?:all |any |the |your |previous |prior |above |earlier )*(?:instructions|rules|prompts?)\b"
                r"|\bsystem prompt\b|\byou are now\b|\bdisregard (?:your|the|all|any|previous)\b"
                r"|\breveal (?:your|the) (?:prompt|instructions)\b"),
     "I can't follow instructions to change how I work; please describe a venue rule."),
    ("concealed",
     re.compile(r"\b(?:conceal\w*|hidden|hiding|hide)\b"),
     "I can't reliably detect concealed objects from a camera. I can monitor visible objects, like bags, "
     "chairs and large cameras, in the zones you've drawn."),
    ("weapon",
     re.compile(r"\b(?:weapons?|guns?|firearms?|knife|knives|pistols?|rifles?|blades?)\b"),
     "I can't reliably recognize weapons, and PolicyLens isn't a weapons detector. Please use dedicated "
     "screening for that."),
    ("identity",
     re.compile(r"\b(?:staff|employees?|vips?|identify|identity|identities|recogni[sz]\w*|faces?|who (?:is|are)"
                r"|specific (?:people|person|individuals?)|security guards?|members? only)\b"),
     "I can't identify people or tell staff from guests. PolicyLens doesn't use face recognition."),
    ("demographic",
     re.compile(r"\b(?:age|ages|aged|minors?|underage|kids|children|gender|male|female|ethnic\w*|race|racial"
                r"|religio\w*)\b"),
     "I can't infer personal characteristics like age or gender. I can monitor objects such as bags, chairs "
     "and large cameras in your zones."),
    ("behavior",
     re.compile(r"\b(?:suspicious\w*|behaviou?r\w*|intent\w*|drunk|intoxicated|fight\w*|aggressive\w*|angry"
                r"|mood|loiter\w*|threat\w*|steal\w*|theft|shoplift\w*)\b"),
     "I can't judge intent or behavior. I can monitor where specific objects are and for how long."),
    ("sound",
     re.compile(r"\b(?:sounds?|noise|noisy|loud|shout\w*|scream\w*|yell\w*|alarms?|hear|audio)\b"),
     "I can't hear anything; these cameras only see. I can monitor visible objects in the zones you've drawn."),
    ("crowd",
     re.compile(r"\b(?:crowd\w*|capacity|how many|occupancy|headcount|too many people)\b"),
     "I can't count crowds or check capacity yet. I can monitor specific objects in the zones you've drawn."),
    ("outside_view",
     re.compile(r"\b(?:outside (?:the )?(?:camera|view|frame)|off[- ]camera|whole (?:venue|building)|everywhere)\b"),
     "I can't monitor areas outside the camera view. I can only watch zones you've drawn on a camera."),
]


def classify_unsupported(text: str) -> str | None:
    """The canonical honest sentence for an unobservable request, or None."""
    low = text.lower()
    for _, pattern, sentence in UNSUPPORTED_TOPICS:
        if pattern.search(low):
            return sentence
    return None
