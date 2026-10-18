"""Construction-site safety gear: hard hats and hi-vis vests on people. Needs the PPE contract change."""

import pytest

from policy.compiler import compile_policy
from policy.contracts import Zone
from policy.describe import describe_rule
from policy.draft import build_draft_schema
from policy.prompts import build_system_prompt
from policy.synonyms import ppe_supported
from policy.tests.test_compiler import ZONES

pytestmark = pytest.mark.skipif(not ppe_supported(), reason="contracts do not allow hard_hat/safety_vest on person yet")

SQUARE = [(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)]
SITE = [Zone(id="construction_zone", name="Construction zone", camera_id="cam_site", polygon=SQUARE)]


def summary(result):
    return [(r.id, r.zone, r.objects, r.attribute.name, r.attribute.expected, r.severity) for r in result.rules]


def test_hard_hat_and_vest():
    result = compile_policy("In the construction zone, everyone must wear a hard hat and a safety vest.", SITE)
    assert summary(result) == [
        ("hard_hat", "construction_zone", ["person"], "hard_hat", True, "review"),
        ("safety_vest", "construction_zone", ["person"], "safety_vest", True, "review"),
    ]
    assert result.warnings == [] and result.unsupported == []
    assert [describe_rule(r, SITE) for r in result.rules] == [
        "Person probably without a hard hat", "Person probably without a safety vest"]


def test_ppe_means_both():
    result = compile_policy("PPE is required for all workers in the construction zone.", SITE)
    assert [r.id for r in result.rules] == ["hard_hat", "safety_vest"]
    assert result.unsupported == []  # "workers" says who the rule covers; it is not an identity request


def test_helmet_only_and_hi_vis_only():
    assert [r.id for r in compile_policy("Helmets must be worn in the construction zone.", SITE).rules] == ["hard_hat"]
    assert [r.id for r in compile_policy("No one enters the construction zone without hi-vis.", SITE).rules] == ["safety_vest"]


def test_other_gear_is_unsupported_but_hard_hat_still_compiles():
    result = compile_policy("In the construction zone, workers need hard hats and gloves.", SITE)
    assert [r.id for r in result.rules] == ["hard_hat"]
    assert len(result.unsupported) == 1 and "gloves" in result.unsupported[0]


def test_employees_wording_is_not_an_identity_request():
    result = compile_policy("All employees must wear safety vests in the construction zone.", SITE)
    assert [r.id for r in result.rules] == ["safety_vest"] and result.unsupported == []


def test_demo_prompt_is_unchanged():
    from policy.tests.test_compiler import DEMO, EXPECTED_DEMO

    assert compile_policy(DEMO, ZONES).model_dump() == EXPECTED_DEMO


def test_schema_and_prompt_offer_ppe():
    options = build_draft_schema(SITE)["properties"]["rules"]["items"]["properties"]["attribute_name"]["anyOf"]
    enum = next(o["enum"] for o in options if "enum" in o)
    assert "hard_hat" in enum and "safety_vest" in enum
    assert "safety_vest" in build_system_prompt()
