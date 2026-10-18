"""capability.py and the few-shot examples, all offline."""

import json
from pathlib import Path

import pytest

from policy.capability import finalize
from policy.contracts import Zone

SQUARE = [(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)]
from policy.draft import DraftPolicy, DraftRule, build_draft_schema
from policy.prompts import FEW_SHOTS
from policy.synonyms import parse_duration

ZONES = [Zone.model_validate(z) for z in json.loads((Path(__file__).parent / "fixtures" / "zones_demo.json").read_text())]


def draft(**overrides) -> DraftPolicy:
    rule = dict(source_text="test rule", type="persistent_object", objects=["chair"], zone_id="emergency_exit",
                attribute_name=None, attribute_expected=None, duration_seconds=5, severity="urgent")
    rule.update(overrides)
    return DraftPolicy(rules=[DraftRule(**rule)], unsupported=[], ambiguities=[])


def test_person_removed_from_persistent_rule():
    result = finalize(draft(objects=["person", "chair"]), ZONES)
    assert result.rules[0].objects == ["chair"]


def test_person_only_persistent_rule_is_dropped():
    result = finalize(draft(objects=["person"]), ZONES)
    assert result.rules == [] and "People can't" in result.warnings[0]


def test_cameras_are_removed_from_persistent_rules():
    """The Rule contract only allows bags and chairs in persistent rules."""
    mixed = finalize(draft(objects=["camera", "chair"]), ZONES)
    assert mixed.rules[0].objects == ["chair"] and any("Removed camera" in w for w in mixed.warnings)
    only_camera = finalize(draft(objects=["camera"]), ZONES)
    assert only_camera.rules == [] and "only watch bags and chairs" in only_camera.warnings[0]


def test_attribute_not_allowed_for_object():
    result = finalize(draft(type="object_attribute", objects=["chair", "backpack"], attribute_name="transparent",
                            attribute_expected=True, zone_id="main_entrance"), ZONES)
    assert result.rules[0].objects == ["backpack"]
    assert any("Removed chair" in w for w in result.warnings)


def test_object_attribute_without_attribute_becomes_persistent():
    result = finalize(draft(type="object_attribute"), ZONES)
    assert result.rules[0].type == "persistent_object"


def test_duration_is_clamped():
    assert finalize(draft(duration_seconds=5000), ZONES).rules[0].duration_seconds == 600
    assert finalize(draft(duration_seconds=0.1), ZONES).rules[0].duration_seconds == 0.5


def test_invalid_zone_id_is_treated_as_unknown():
    result = finalize(draft(zone_id="made_up"), ZONES)
    assert result.rules == [] and result.warnings[0].startswith("Which zone")


def test_missing_severity_defaults_from_text():
    assert finalize(draft(severity=None, source_text="keep the exit clear"), ZONES).rules[0].severity == "urgent"
    assert finalize(draft(severity=None, source_text="no luggage here", zone_id="main_entrance"),
                    ZONES).rules[0].severity == "review"


def test_duplicate_ids_get_suffixes_and_exact_duplicates_merge():
    a = DraftRule(source_text="a", type="persistent_object", objects=["chair"], zone_id="emergency_exit",
                  attribute_name=None, attribute_expected=None, duration_seconds=5, severity="urgent")
    b = a.model_copy(update={"duration_seconds": 20})
    result = finalize(DraftPolicy(rules=[a, a, b], unsupported=[], ambiguities=[]), ZONES)
    assert [r.id for r in result.rules] == ["blocked_exit", "blocked_exit_2"]


def test_zone_name_on_two_cameras_warns():
    zones = [Zone(id="entrance_a", name="Entrance", camera_id="cam_a", polygon=SQUARE),
             Zone(id="entrance_b", name="Entrance", camera_id="cam_b", polygon=SQUARE)]
    result = finalize(draft(zone_id="entrance_a", source_text="no chairs at the entrance"), zones)
    assert any("more than one camera" in w for w in result.warnings)


def test_unsupported_entries_are_normalized():
    d = DraftPolicy(rules=[], ambiguities=[], unsupported=[
        "Weapons are not detectable.", "I can't hear sounds.", "I can't hear sounds.", "  ",
    ])
    result = finalize(d, ZONES)
    assert result.unsupported[0].startswith("I can't reliably recognize weapons")
    assert result.unsupported[1] == "I can't hear sounds."
    assert len(result.unsupported) == 2


def test_phone_warning_only_for_generic_camera_rules():
    plain = finalize(draft(type="object_attribute", objects=["camera"], attribute_name="professional",
                           attribute_expected=False, zone_id="main_entrance", source_text="No cameras"), ZONES)
    assert any("phones" in w for w in plain.warnings)
    pro = finalize(draft(type="object_attribute", objects=["camera"], attribute_name="professional",
                         attribute_expected=False, zone_id="main_entrance",
                         source_text="professional cameras require review"), ZONES)
    assert pro.warnings == []


@pytest.mark.parametrize("zones,policy,output", FEW_SHOTS)
def test_few_shots_are_valid_and_pass_capability(zones, policy, output):
    zone_models = [Zone(polygon=SQUARE, **z) for z in zones]
    result = finalize(DraftPolicy.model_validate(output), zone_models)
    assert len(result.rules) == len(output["rules"])
    assert len(result.unsupported) == len(output["unsupported"])


def test_schema_has_zone_enum_and_no_refs():
    schema = build_draft_schema(ZONES)
    text = json.dumps(schema)
    assert "$ref" not in text and "$defs" not in text
    assert schema["properties"]["rules"]["items"]["properties"]["zone_id"]["enum"] == [
        "main_entrance", "emergency_exit", "UNKNOWN"]


@pytest.mark.parametrize("text,seconds", [
    ("for more than five seconds", 5), ("half a minute", 30), ("2 min", 120), ("over 5 s", 5),
    ("a minute", 60), ("1.5 minutes", 90), ("a 10-second wait", 10), ("as soon as possible", None),
    ("keep it clear", None),
])
def test_parse_duration(text, seconds):
    assert parse_duration(text) == seconds
