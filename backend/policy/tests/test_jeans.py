"""Dress code: "No jeans" checks each person's crop for jeans (expected false)."""

import pytest

from policy.compiler import compile_policy
from policy.contracts import Zone
from verify.prompts import CHECK_FOR_ATTRIBUTE, QUESTIONS

FULL = [(0, 0), (1, 0), (1, 1), (0, 1)]
PLAZA = [Zone(id="plaza_frame", camera_id="cam_plaza", name="Plaza", polygon=FULL)]
DRAWN = [Zone(id="lobby", camera_id="cam_a", name="Lobby", polygon=[(0.1, 0.1), (0.6, 0.1), (0.6, 0.9)]),
         Zone(id="gate", camera_id="cam_b", name="Gate", polygon=[(0.1, 0.1), (0.6, 0.1), (0.6, 0.9)])]


def jeans_rules(result):
    return [(r.id, r.objects, r.attribute.expected, r.zone) for r in result.rules if r.attribute and r.attribute.name == "jeans"]


@pytest.mark.parametrize("policy", ["No jeans.", "Jeans are not allowed.", "No denim, please."])
def test_jeans_ban_compiles_to_one_check_per_camera(policy):
    result = compile_policy(policy, PLAZA)
    assert jeans_rules(result) == [("jeans", ["person"], False, "plaza_frame")]
    assert result.rules[0].name == "Jeans policy" and result.rules[0].severity == "review"
    assert result.warnings == [] and result.unsupported == []


def test_jeans_required_expects_true():
    assert jeans_rules(compile_policy("Jeans required.", PLAZA)) == [("jeans", ["person"], True, "plaza_frame")]


def test_drawn_zones_keep_their_scope():
    result = compile_policy("No jeans in the lobby.", DRAWN)
    assert jeans_rules(result) == [("jeans", ["person"], False, "lobby")]


def test_other_clothing_is_honestly_unsupported():
    result = compile_policy("No jeans or shorts.", PLAZA)
    assert len(jeans_rules(result)) == 1
    assert any("other than jeans" in note for note in result.unsupported)
    assert compile_policy("Hats are not allowed.", PLAZA).rules == []


def test_jeans_rule_is_not_an_object_ban():
    # The no_ id prefix marks object bans ("No bags"); a jeans rule must not use it.
    assert not compile_policy("No jeans.", PLAZA).rules[0].id.startswith("no_")


def test_verifier_has_a_jeans_question():
    assert CHECK_FOR_ATTRIBUTE["jeans"] == "jeans"
    assert "jeans" in QUESTIONS["jeans"].lower()


@pytest.mark.live
def test_live_no_jeans():
    result = compile_policy("No jeans.", PLAZA)
    assert jeans_rules(result) == [("jeans", ["person"], False, "plaza_frame")]
    assert result.unsupported == []
