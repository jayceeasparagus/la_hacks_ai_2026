"""Prohibitions ("No bags", "Bags are not allowed"): any such object in view, after a short time."""

import json
from pathlib import Path

import pytest

from policy.capability import finalize
from policy.compiler import compile_policy
from policy.contracts import Zone
from policy.draft import DraftPolicy, DraftRule
from policy.synonyms import BAGS, is_prohibition

FULL = [(0, 0), (1, 0), (1, 1), (0, 1)]
SITE = [Zone(id="site_frame", camera_id="cam_site", name="Construction site", polygon=FULL),
        Zone(id="warehouse_frame", camera_id="cam_warehouse", name="Warehouse", polygon=FULL)]
DRAWN = [Zone.model_validate(z) for z in json.loads(
    (Path(__file__).parent / "fixtures" / "zones_demo.json").read_text(encoding="utf-8"))]
BAG_BANS = ["No backpacks or bags.", "no backpack/bags", "Bags are not allowed."]


def summary(result):
    return [(r.id, r.name, r.type, r.objects, r.zone, r.duration_seconds, r.severity, r.attribute)
            for r in result.rules]


def no_bags(rule_id, zone):
    return (rule_id, "No-bag policy", "persistent_object", BAGS, zone, 1.0, "review", None)


@pytest.mark.parametrize("prompt", BAG_BANS)
def test_bag_ban_covers_every_whole_frame_camera(prompt):
    result = compile_policy(prompt, SITE)
    assert summary(result) == [no_bags("no_bags", "site_frame"), no_bags("no_bags_2", "warehouse_frame")]
    assert result.warnings == [] and result.unsupported == []


@pytest.mark.parametrize("prompt", BAG_BANS)
def test_bag_ban_in_a_drawn_zone(prompt):
    result = compile_policy(f"At the main entrance: {prompt}", DRAWN)
    assert summary(result) == [no_bags("no_bags", "main_entrance")]
    assert result.warnings == [] and result.unsupported == []


@pytest.mark.parametrize("prompt", BAG_BANS)
def test_bag_ban_naming_no_drawn_zone_asks_which(prompt):
    result = compile_policy(prompt, DRAWN)
    assert result.rules == []
    assert any("Which zone" in w for w in result.warnings)


def test_other_objects_generalize():
    chairs = compile_policy("No chairs.", SITE)
    assert [(r.id, r.name, r.objects, r.duration_seconds) for r in chairs.rules] == [
        ("no_chairs", "No-chair policy", ["chair"], 1.0), ("no_chairs_2", "No-chair policy", ["chair"], 1.0)]
    both = compile_policy("Bags and chairs are prohibited in the Main entrance.", DRAWN)
    assert [(r.id, r.objects) for r in both.rules] == [("no_objects", BAGS + ["chair"])]
    luggage = compile_policy("Don't let anyone bring luggage.", SITE)
    assert [(r.id, r.objects) for r in luggage.rules] == [("no_bags", ["suitcase"]), ("no_bags_2", ["suitcase"])]


def test_ban_at_an_exit_is_urgent():
    result = compile_policy("No bags at the emergency exit.", DRAWN)
    assert [(r.id, r.zone, r.duration_seconds, r.severity) for r in result.rules] == [
        ("no_bags", "emergency_exit", 1.0, "urgent")]


def test_bans_on_what_cannot_be_flagged_are_honest():
    cameras = compile_policy("No cameras.", SITE)
    assert {r.id for r in cameras.rules} == {"pro_camera", "pro_camera_2"}
    assert any("professional-style" in w for w in cameras.warnings)
    people = compile_policy("No people allowed.", SITE)
    assert people.rules == [] and "every person" in people.unsupported[0]
    smoking = compile_policy("No smoking.", SITE)
    assert smoking.rules == [] and smoking.unsupported[0].startswith("I can't")


def test_unattended_and_timed_wording_is_not_a_ban():
    unattended = compile_policy("No bags left unattended.", SITE)
    assert {r.id for r in unattended.rules} == {"unattended_bag", "unattended_bag_2"}
    assert unattended.rules[0].duration_seconds == 10.0
    timed = compile_policy("No bags for more than 30 seconds.", SITE)
    assert [(r.id, r.duration_seconds) for r in timed.rules] == [("unattended_bag", 30.0), ("unattended_bag_2", 30.0)]
    for text in ("Keep the emergency exit clear.", "Only clear bags are permitted.",
                 "Alert if a bag stays for no more than 5 seconds.", "No one may leave bags here."):
        assert not is_prohibition(text), text


def test_a_model_answer_is_normalized():
    """What live Gemini returned before the fix: a 10 s rule with a time-limit note."""
    draft = DraftPolicy(rules=[DraftRule(
        source_text="No backpacks or bags.", type="persistent_object", objects=BAGS,
        zone_id="site_frame", attribute_name=None, attribute_expected=None, duration_seconds=10, severity=None,
    )], unsupported=[], ambiguities=["No time limit was given for bags."])
    result = finalize(draft, SITE)
    assert summary(result) == [no_bags("no_bags", "site_frame"), no_bags("no_bags_2", "warehouse_frame")]
    assert result.warnings == []


@pytest.mark.live
def test_live_bag_ban():
    from policy.compiler import compile_policy_with_info

    result, info = compile_policy_with_info("No backpacks or bags.", SITE)
    print(f"\n[{info.source} {info.model}] {info.latency_ms} ms: {summary(result)} {result.warnings}")
    assert info.source == "gemini"
    assert [(r.id, r.zone, r.duration_seconds, r.severity) for r in result.rules] == [
        ("no_bags", "site_frame", 1.0, "review"), ("no_bags_2", "warehouse_frame", 1.0, "review")]
    assert all(set(r.objects) == set(BAGS) for r in result.rules)
    assert result.warnings == [] and result.unsupported == []
