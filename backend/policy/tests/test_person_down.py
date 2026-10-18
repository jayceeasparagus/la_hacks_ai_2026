"""Stretch goal: person down. Off until the contracts support lying_down; tested both ways."""

import json
from typing import Literal

import pytest

from policy import capability, contracts, llm
from policy.compiler import compile_policy
from policy.contracts import Attribute
from policy.describe import describe_rule
from policy.draft import build_draft_schema
from policy.prompts import build_system_prompt
from policy.synonyms import PERSON_DOWN_UNSUPPORTED
from policy.tests.test_compiler import ZONES

PROMPT = "Alert if someone is on the floor at the main entrance for more than 10 seconds."


@pytest.fixture
def enabled(monkeypatch):
    """Simulate Person 4's contract change: lying_down allowed on person."""

    class ExtendedAttribute(Attribute):
        name: Literal["transparent", "professional", "lying_down"]

    monkeypatch.setitem(contracts.SUPPORTED_ATTRIBUTES, "lying_down", ["person"])
    monkeypatch.setattr(capability, "Attribute", ExtendedAttribute)


def attribute_enum() -> list[str]:
    schema = build_draft_schema(ZONES)
    options = schema["properties"]["rules"]["items"]["properties"]["attribute_name"]["anyOf"]
    return next(o["enum"] for o in options if "enum" in o)


def test_disabled_reports_unsupported():
    result = compile_policy(PROMPT, ZONES)
    assert result.rules == []
    assert result.unsupported == [PERSON_DOWN_UNSUPPORTED]


def test_disabled_schema_and_prompt():
    assert "lying_down" not in attribute_enum()
    assert "cannot be checked yet" in build_system_prompt()


def test_disabled_model_rule_on_people_becomes_unsupported(monkeypatch):
    """If Gemini still writes a person rule for a collapse, report it honestly instead of a vague warning."""
    monkeypatch.delenv("POLICYLENS_FAKE_LLM", raising=False)
    draft = {"rules": [{"source_text": "alert if someone collapses", "type": "persistent_object",
                        "objects": ["person"], "zone_id": "main_entrance", "attribute_name": None,
                        "attribute_expected": None, "duration_seconds": 10, "severity": "urgent"}],
             "unsupported": [], "ambiguities": []}
    monkeypatch.setattr(llm, "call_structured", lambda *a, **k: json.dumps(draft))
    result = compile_policy("alert if someone collapses", ZONES)
    assert result.rules == [] and result.unsupported == [PERSON_DOWN_UNSUPPORTED]


def test_enabled_builds_the_rule(enabled):
    result = compile_policy(PROMPT, ZONES)
    assert result.unsupported == [] and result.warnings == []
    rule = result.rules[0].model_dump()
    assert rule == {
        "id": "person_down", "name": "Possible person down", "type": "persistent_object",
        "objects": ["person"], "zone": "main_entrance",
        "attribute": {"name": "lying_down", "expected": False},
        "duration_seconds": 10, "severity": "urgent", "enabled": True,
    }
    assert describe_rule(result.rules[0], ZONES) == "Person probably down for 10 seconds"


def test_enabled_default_duration(enabled):
    result = compile_policy("Tell me if anyone collapses at the main entrance.", ZONES)
    assert result.rules[0].duration_seconds == 10
    assert any("using 10 seconds" in w for w in result.warnings)


def test_enabled_schema_and_prompt(enabled):
    assert "lying_down" in attribute_enum()
    prompt = build_system_prompt()
    assert "lying_down" in prompt and "cannot be checked yet" not in prompt


def test_people_still_never_count_for_ordinary_persistent_rules(enabled):
    result = compile_policy("Don't let anyone leave a bag at the main entrance for 20 seconds.", ZONES)
    assert [r.objects for r in result.rules] == [["backpack", "handbag", "suitcase"]]
