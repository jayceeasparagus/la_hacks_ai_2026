"""Gemini failure modes through the real llm wrapper: no network, bad key, quota, slow, fenced JSON.
A fake client stands in for google-genai, so these run offline."""

import json
import time
from types import SimpleNamespace

import httpx
import numpy as np
import pytest

from policy import compiler, llm
from policy.compiler import compile_policy_with_info
from policy.prompts import FEW_SHOTS
from policy.tests.test_compiler import DEMO, EXPECTED_DEMO, ZONES
from verify.verifier import verify_crop

GOOD_DRAFT = json.dumps(FEW_SHOTS[0][2])


class FakeClient:
    def __init__(self, behavior):
        self.calls = 0
        self.behavior = behavior
        self.interactions = SimpleNamespace(create=self.create)

    def create(self, **kwargs):
        self.calls += 1
        result = self.behavior(kwargs)
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(output_text=result)


@pytest.fixture
def client(monkeypatch):
    """Real (non-FAKE) path with a fake client; set client.behavior per test."""
    monkeypatch.delenv("POLICYLENS_FAKE_LLM", raising=False)
    fake = FakeClient(lambda kwargs: GOOD_DRAFT)
    monkeypatch.setattr(llm, "get_client", lambda: fake)
    return fake


FAILURES = {
    "wifi_off": httpx.ConnectError("[Errno 11001] getaddrinfo failed"),
    "invalid_key": RuntimeError("Error code: 400 - API key not valid. Please pass a valid API key."),
    "quota": RuntimeError("Error code: 429 - RESOURCE_EXHAUSTED: quota exceeded"),
}


@pytest.mark.parametrize("name", FAILURES)
def test_compile_degrades_to_fallback(client, name):
    client.behavior = lambda kwargs: FAILURES[name]
    result, info = compile_policy_with_info(DEMO, ZONES)
    assert result.model_dump() == EXPECTED_DEMO
    assert info.source == "fallback"
    assert client.calls == 2


@pytest.mark.parametrize("name", FAILURES)
def test_verify_degrades_to_unavailable(client, name):
    client.behavior = lambda kwargs: FAILURES[name]
    verdict = verify_crop(np.full((100, 100, 3), 200, np.uint8), "transparent_bag")
    assert (verdict.answer, verdict.reason) == (None, "verification unavailable")


def test_breaker_pauses_gemini_after_repeated_failures(client):
    client.behavior = lambda kwargs: FAILURES["wifi_off"]
    compile_policy_with_info(DEMO, ZONES)          # 2 failed attempts
    verify_crop(np.full((100, 100, 3), 1, np.uint8), "transparent_bag")  # 3rd failure opens the breaker
    assert not llm.available()
    assert llm.status()["available"] is False

    calls = client.calls
    started = time.monotonic()
    result, info = compile_policy_with_info("Keep the emergency exit clear for 5 seconds.", ZONES)
    verdict = verify_crop(np.full((100, 100, 3), 2, np.uint8), "transparent_bag")
    assert client.calls == calls, "no Gemini calls while paused"
    assert time.monotonic() - started < 0.5
    assert info.source == "fallback" and [r.id for r in result.rules] == ["blocked_exit"]
    assert verdict.reason == "verification unavailable"


def test_breaker_closes_after_pause(client, monkeypatch):
    monkeypatch.setattr(llm, "PAUSE_SECONDS", 0.05)
    client.behavior = lambda kwargs: FAILURES["quota"]
    for _ in range(llm.FAILURES_TO_PAUSE):
        verify_crop(np.full((100, 100, 3), _ + 10, np.uint8), "transparent_bag")
    assert not llm.available()
    time.sleep(0.1)
    assert llm.available()
    client.behavior = lambda kwargs: GOOD_DRAFT
    assert compile_policy_with_info(DEMO, ZONES)[1].source == "gemini"


def test_success_resets_failure_count(client):
    vision_ok = json.dumps({"answer": "yes", "confidence": 0.9, "reason": "clear vinyl tote"})
    replies = iter([FAILURES["quota"], FAILURES["quota"], vision_ok, FAILURES["quota"], FAILURES["quota"]])
    client.behavior = lambda kwargs: next(replies)
    compile_policy_with_info(DEMO, ZONES)                                   # 2 failures
    assert verify_crop(np.full((100, 100, 3), 5, np.uint8), "transparent_bag").answer is True  # success resets
    compile_policy_with_info("Keep the emergency exit clear.", ZONES)       # 2 more failures
    assert llm.available()


def test_slow_gemini_hits_the_compile_deadline(client, monkeypatch):
    monkeypatch.setattr(compiler, "TOTAL_TIMEOUT_S", 1.5)
    client.behavior = lambda kwargs: time.sleep(3) or GOOD_DRAFT
    started = time.monotonic()
    result, info = compile_policy_with_info(DEMO, ZONES)
    assert time.monotonic() - started < 2.5
    assert info.source == "fallback" and result.model_dump() == EXPECTED_DEMO


def test_fenced_json_is_accepted(client):
    client.behavior = lambda kwargs: f"```json\n{GOOD_DRAFT}\n```"
    result, info = compile_policy_with_info(DEMO, ZONES)
    assert info.source == "gemini" and result.model_dump() == EXPECTED_DEMO


def test_request_shape(client):
    """What we send: schema in response_format, system instruction, our own timeout."""
    seen = {}
    client.behavior = lambda kwargs: seen.update(kwargs) or GOOD_DRAFT
    compile_policy_with_info(DEMO, ZONES)
    assert seen["response_format"]["type"] == "text"
    assert seen["response_format"]["mime_type"] == "application/json"
    assert "zone_id" in json.dumps(seen["response_format"]["schema"])
    assert "PolicyLens" in seen["system_instruction"]
    assert "<policy>" in seen["input"] and 0 < seen["timeout"] <= compiler.TOTAL_TIMEOUT_S


def test_verify_request_uses_minimal_thinking_and_an_image(client):
    seen = {}
    client.behavior = lambda kwargs: seen.update(kwargs) or json.dumps(
        {"answer": "no", "confidence": 0.8, "reason": "black fabric backpack"})
    verdict = verify_crop(np.full((100, 100, 3), 77, np.uint8), "transparent_bag")
    assert verdict.answer is False
    assert seen["generation_config"] == {"thinking_level": "minimal"}
    assert [part["type"] for part in seen["input"]] == ["text", "image"]
    assert seen["input"][1]["mime_type"] == "image/jpeg"


def test_status_reports_mode_and_models(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")
    monkeypatch.delenv("GEMINI_VERIFY_MODEL", raising=False)
    status = llm.status()
    assert status["mode"] == "fake" and status["policy_model"] == status["verify_model"] == "gemini-test"


@pytest.mark.parametrize("text,expected", [
    ('{"a": 1}', '{"a": 1}'), ('```json\n{"a": 1}\n```', '{"a": 1}'), ('```\n{"a": 1}```', '{"a": 1}'),
])
def test_strip_fences(text, expected):
    assert llm.strip_fences(text) == expected
