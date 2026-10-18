"""Whole-frame cameras (the site safety demo): no zones to choose, every rule covers every camera."""

import pytest

from policy.capability import whole_frame_cameras
from policy.compiler import compile_policy
from policy.contracts import Zone

FULL = [(0, 0), (1, 0), (1, 1), (0, 1)]
SITE = [Zone(id="site_frame", camera_id="cam_site", name="Construction site", polygon=FULL),
        Zone(id="warehouse_frame", camera_id="cam_warehouse", name="Warehouse", polygon=FULL)]
EXAMPLE = "Workers at the construction site need to wear a vest and a helmet."


def gear(result):
    return sorted((r.attribute.name, r.zone) for r in result.rules)


def test_whole_frame_detection():
    assert whole_frame_cameras(SITE)
    inset = [(0.02, 0.02), (0.98, 0.02), (0.98, 0.98), (0.02, 0.98)]  # still (almost) the whole frame
    assert whole_frame_cameras([z.model_copy(update={"polygon": inset}) for z in SITE])
    half = [(0, 0), (0.5, 0), (0.5, 1), (0, 1)]
    assert not whole_frame_cameras([SITE[0].model_copy(update={"polygon": half}), SITE[1]])
    two_on_one_camera = [SITE[0], SITE[1].model_copy(update={"camera_id": "cam_site"})]
    assert not whole_frame_cameras(two_on_one_camera)
    assert not whole_frame_cameras([])


def test_example_sentence_covers_every_camera_offline():
    result = compile_policy(EXAMPLE, SITE)
    assert gear(result) == [("hard_hat", "site_frame"), ("hard_hat", "warehouse_frame"),
                            ("safety_vest", "site_frame"), ("safety_vest", "warehouse_frame")]
    assert {r.id for r in result.rules} == {"hard_hat", "hard_hat_2", "safety_vest", "safety_vest_2"}
    assert all(r.objects == ["person"] and r.attribute.expected is True and r.severity == "review"
               for r in result.rules)
    assert result.warnings == [] and result.unsupported == []


def test_a_policy_naming_no_place_needs_no_zone():
    result = compile_policy("Everyone must wear a hard hat.", SITE)
    assert gear(result) == [("hard_hat", "site_frame"), ("hard_hat", "warehouse_frame")]
    assert result.warnings == []


def test_a_place_that_is_not_a_camera_still_applies_everywhere():
    result = compile_policy("Alert if anyone leaves a bag at the loading dock for more than a minute.", SITE)
    assert sorted(r.zone for r in result.rules) == ["site_frame", "warehouse_frame"]
    assert not any("Which zone" in w for w in result.warnings)


def test_unsupported_gear_is_still_reported():
    result = compile_policy("Everyone must wear a hard hat and gloves.", SITE)
    assert gear(result) == [("hard_hat", "site_frame"), ("hard_hat", "warehouse_frame")]
    assert result.unsupported


@pytest.mark.live
def test_live_example_sentence_covers_every_camera():
    result = compile_policy(EXAMPLE, SITE)
    assert gear(result) == [("hard_hat", "site_frame"), ("hard_hat", "warehouse_frame"),
                            ("safety_vest", "site_frame"), ("safety_vest", "warehouse_frame")]
    assert result.unsupported == []
