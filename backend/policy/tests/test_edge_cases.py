"""Regression tests for bugs found in review: fallback regexes, zone matching, ids, NaN durations."""

import json

from policy import cache, llm
from policy.compiler import compile_policy, compile_policy_with_info
from policy.contracts import Zone
from policy.synonyms import parse_duration
from policy.tests.test_compiler import ZONES


def zone(zone_id, name, camera="cam_1"):
    return Zone(id=zone_id, name=name, camera_id=camera, polygon=[])


def summary(result):
    return [(r.id, r.zone, r.type) for r in result.rules]


def test_nan_duration_from_gemini_uses_the_default(monkeypatch):
    monkeypatch.delenv("POLICYLENS_FAKE_LLM", raising=False)
    draft = ('{"rules": [{"source_text": "keep the exit clear", "type": "persistent_object", "objects": ["chair"], '
             '"zone_id": "emergency_exit", "attribute_name": null, "attribute_expected": null, '
             '"duration_seconds": NaN, "severity": "urgent"}], "unsupported": [], "ambiguities": []}')
    monkeypatch.setattr(llm, "call_structured", lambda *a, **k: draft)
    result, info = compile_policy_with_info("keep the exit clear", ZONES)
    assert info.source == "gemini" and result.rules[0].duration_seconds == 10
    cache.clear_memory()
    assert compile_policy_with_info("keep the exit clear", ZONES)[1].source == "cache"  # readable from disk


def test_clear_of_bags_is_not_a_clear_bag_rule():
    result = compile_policy("Keep the emergency exit clear of bags and chairs for more than 5 seconds.", ZONES)
    assert summary(result) == [("blocked_exit", "emergency_exit", "persistent_object")]
    assert result.rules[0].duration_seconds == 5


def test_clear_bags_at_two_zones_is_not_an_exit_rule():
    result = compile_policy("Only clear bags at the main entrance and the emergency exit.", ZONES)
    assert summary(result) == [("clear_bag", "main_entrance", "object_attribute"),
                               ("clear_bag_2", "emergency_exit", "object_attribute")]


def test_bag_on_the_floor_is_a_bag_rule_not_person_down():
    result = compile_policy(
        "Alert if anyone leaves a bag on the floor by the emergency exit for more than a minute.", ZONES)
    assert result.unsupported == []
    assert [(r.zone, r.objects, r.duration_seconds) for r in result.rules] == [
        ("emergency_exit", ["backpack", "handbag", "suitcase"], 60)]


def test_hyphenated_number_words():
    assert parse_duration("for twenty-five seconds") == 25
    assert parse_duration("thirty five seconds") == 35
    assert parse_duration("forty-five seconds") == 45
    result = compile_policy("Alert if a chair blocks the emergency exit for twenty-five seconds.", ZONES)
    assert result.rules[0].duration_seconds == 25


def test_numbered_zones_pick_the_exact_one():
    zones = [zone("gate_1", "Gate 1"), zone("gate_12", "Gate 12")]
    result = compile_policy("Don't let chairs block gate 12 for more than 5 seconds.", zones)
    assert [r.zone for r in result.rules] == ["gate_12"]
    assert result.warnings == []


def test_rule_ids_are_always_unique():
    zones = [zone("stage", "Stage"), zone("stage_2", "Stage 2", "cam_2")]
    result = compile_policy(
        "Chairs can't block the stage for 5 seconds. Bags can't block the stage for 20 seconds. "
        "Chairs can't block stage 2 for 5 seconds.", zones)
    ids = [r.id for r in result.rules]
    assert len(ids) == 3 and len(set(ids)) == 3


def test_zone_names_do_not_trigger_unsupported():
    zones = [zone("vip_lounge", "VIP lounge"), zone("staff_entrance", "Staff entrance", "cam_2")]
    lounge = compile_policy("Alert if a bag is left in the VIP lounge for more than 2 minutes.", zones)
    assert lounge.unsupported == [] and summary(lounge) == [("unattended_bag", "vip_lounge", "persistent_object")]
    entrance = compile_policy("Don't let anyone leave a suitcase at the staff entrance for 30 seconds.", zones)
    assert entrance.unsupported == [] and [r.zone for r in entrance.rules] == ["staff_entrance"]
    staff = compile_policy("Only staff in the VIP lounge.", zones)
    assert len(staff.unsupported) == 1  # a real identity request is still reported


def test_exit_clear_of_people_warns_instead_of_guessing_objects():
    result = compile_policy("Keep the emergency exit clear of people.", ZONES)
    assert result.rules == []
    assert any("People can't" in w for w in result.warnings)


def test_left_behind_rule_uses_the_previous_sentence_zone():
    result = compile_policy("This is about the main entrance. Don't leave suitcases there for 2 minutes.", ZONES)
    assert [(r.zone, r.duration_seconds) for r in result.rules] == [("main_entrance", 120)]


def test_cache_key_includes_version(monkeypatch):
    key = cache.make_key("p", ZONES, "m")
    monkeypatch.setattr(cache, "CACHE_VERSION", cache.CACHE_VERSION + 1)
    assert cache.make_key("p", ZONES, "m") != key
