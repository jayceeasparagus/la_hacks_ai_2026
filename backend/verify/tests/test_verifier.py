"""Verifier tests. Offline by default; `pytest -m live` sends one synthetic crop to Gemini."""

import json
import threading
import time
from concurrent.futures import Future

import cv2
import numpy as np
import pytest

from policy import llm
from verify import ratelimit, verifier
from verify.ratelimit import RateLimiter
from verify.verifier import VisionAnswer, encode_jpeg, to_verdict, verify_crop

BRIGHT = np.full((120, 80, 3), 220, np.uint8)
DARK = np.full((120, 80, 3), 30, np.uint8)


def real_path(monkeypatch, respond):
    """Turn FAKE mode off and make submit_structured call `respond()` instead of Gemini."""
    monkeypatch.delenv("POLICYLENS_FAKE_LLM", raising=False)
    calls = []

    def submit(*args, **kwargs):
        calls.append(kwargs)
        return respond()

    monkeypatch.setattr(llm, "submit_structured", submit)
    return calls


def done(text: str) -> Future:
    future = Future()
    future.set_result(text)
    return future


def answer(ans="yes", confidence=0.9, reason="clear plastic tote") -> str:
    return json.dumps({"answer": ans, "confidence": confidence, "reason": reason})


def test_too_small_crop_skips_the_model(monkeypatch):
    calls = real_path(monkeypatch, lambda: done(answer()))
    verdict = verify_crop(np.zeros((30, 200, 3), np.uint8), "transparent_bag")
    assert (verdict.answer, verdict.confidence, verdict.reason) == (None, 0, "object too small to judge")
    assert calls == []


@pytest.mark.parametrize("crop", [None, np.zeros(100, np.uint8), "not an image"])
def test_garbage_input_never_raises(crop):
    assert verify_crop(crop, "transparent_bag").answer is None


def test_unknown_check_never_raises():
    assert verify_crop(BRIGHT, "no_such_check").answer is None


def test_fake_mode_is_deterministic():
    assert verify_crop(BRIGHT, "transparent_bag").answer is True
    assert verify_crop(DARK, "transparent_bag").answer is False
    assert verify_crop(DARK, "professional_camera").answer is True
    assert verify_crop(BRIGHT, "professional_camera").answer is False


def test_fake_person_down_uses_box_shape():
    assert verify_crop(np.zeros((80, 200, 3), np.uint8), "person_down").answer is True
    assert verify_crop(np.zeros((200, 80, 3), np.uint8), "person_down").answer is False


def test_fake_ppe_uses_regions():
    helmet = np.zeros((200, 80, 3), np.uint8)
    helmet[:50] = 230  # bright top quarter
    assert verify_crop(helmet, "hard_hat").answer is True
    assert verify_crop(helmet, "safety_vest").answer is False
    vest = np.zeros((200, 80, 3), np.uint8)
    vest[50:150] = 230  # bright middle half
    assert verify_crop(vest, "safety_vest").answer is True
    assert verify_crop(vest, "hard_hat").answer is False


def test_every_attribute_has_a_check():
    from verify.prompts import CHECK_FOR_ATTRIBUTE, QUESTIONS

    assert set(CHECK_FOR_ATTRIBUTE.values()) == set(QUESTIONS)


def test_encode_resizes_longer_side_to_512():
    image = np.random.default_rng(0).integers(0, 255, (600, 1000, 3), dtype=np.uint8)
    decoded = cv2.imdecode(np.frombuffer(encode_jpeg(image), np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape[:2] == (307, 512)
    small = cv2.imdecode(np.frombuffer(encode_jpeg(BRIGHT), np.uint8), cv2.IMREAD_COLOR)
    assert small.shape[:2] == (120, 80)


def test_answers_map_to_verdicts(monkeypatch):
    replies = iter([answer("yes"), answer("no"), answer("unclear", 0.9)])
    real_path(monkeypatch, lambda: done(next(replies)))
    crops = [np.full((100, 100, 3), v, np.uint8) for v in (10, 20, 30)]
    assert [verify_crop(c, "transparent_bag").answer for c in crops] == [True, False, None]


def test_low_confidence_becomes_unclear(monkeypatch):
    real_path(monkeypatch, lambda: done(answer("yes", 0.4)))
    verdict = verify_crop(BRIGHT, "transparent_bag")
    assert verdict.answer is None and verdict.confidence == 0.4


def test_reason_is_trimmed_to_15_words():
    verdict = to_verdict(VisionAnswer(answer="no", confidence=0.8, reason=" ".join(["word"] * 30)))
    assert len(verdict.reason.split()) == 15


def test_cache_hit_skips_the_model(monkeypatch):
    calls = real_path(monkeypatch, lambda: done(answer()))
    first = verify_crop(BRIGHT, "transparent_bag")
    second = verify_crop(BRIGHT.copy(), "transparent_bag")
    assert first == second and len(calls) == 1
    verify_crop(BRIGHT, "professional_camera")
    assert len(calls) == 2  # the cache is keyed by check too


def test_api_error_is_unavailable(monkeypatch):
    def fail():
        future = Future()
        future.set_exception(RuntimeError("429 quota"))
        return future

    real_path(monkeypatch, fail)
    verdict = verify_crop(BRIGHT, "transparent_bag")
    assert (verdict.answer, verdict.reason) == (None, "verification unavailable")
    assert ratelimit.LIMITER._in_flight == 0


def test_invalid_json_is_unavailable(monkeypatch):
    real_path(monkeypatch, lambda: done('{"answer": "maybe"}'))
    assert verify_crop(BRIGHT, "transparent_bag").reason == "verification unavailable"


def test_timeout_returns_quickly_and_frees_the_slot(monkeypatch):
    monkeypatch.setattr(verifier, "TIMEOUT_S", 0.3)
    future = Future()
    real_path(monkeypatch, lambda: future)
    started = time.monotonic()
    verdict = verify_crop(BRIGHT, "transparent_bag")
    assert verdict.reason == "verification timed out" and verdict.answer is None
    assert time.monotonic() - started < 1.0
    assert ratelimit.LIMITER._in_flight == 1  # the request is still running...
    future.set_result(answer())
    assert ratelimit.LIMITER._in_flight == 0  # ...and frees its slot when it ends


def test_busy_limiter_returns_busy(monkeypatch):
    monkeypatch.setattr(verifier, "BUSY_WAIT_S", 0.05)
    limiter = RateLimiter(rate_per_s=0.01, burst=1)
    assert limiter.acquire(0)
    monkeypatch.setattr(ratelimit, "LIMITER", limiter)
    calls = real_path(monkeypatch, lambda: done(answer()))
    assert verify_crop(BRIGHT, "transparent_bag").reason == "verification busy"
    assert calls == []


def test_rate_limiter_caps_in_flight():
    limiter = RateLimiter(rate_per_s=100, burst=10, max_in_flight=2)
    assert limiter.acquire(0) and limiter.acquire(0)
    assert not limiter.acquire(0.05)
    limiter.release()
    assert limiter.acquire(0.05)


def test_rate_limiter_paces_requests():
    limiter = RateLimiter(rate_per_s=10, burst=1, max_in_flight=10)
    started = time.monotonic()
    for _ in range(4):
        assert limiter.acquire(1)
    assert 0.25 <= time.monotonic() - started < 0.6


def test_many_threads_never_raise(monkeypatch):
    real_path(monkeypatch, lambda: done(answer()))
    results = []

    def worker(value):
        results.append(verify_crop(np.full((90, 90, 3), value, np.uint8), "transparent_bag"))

    threads = [threading.Thread(target=worker, args=(v,)) for v in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 12
    assert {r.reason for r in results} <= {"clear plastic tote", "verification busy"}


@pytest.mark.live
@pytest.mark.parametrize("check", ["transparent_bag", "professional_camera"])
def test_live_synthetic_crop(check):
    image = np.full((300, 300, 3), 235, np.uint8)
    cv2.rectangle(image, (80, 90), (220, 250), (40, 60, 140), -1)  # a solid "bag"-ish block
    started = time.monotonic()
    verdict = verify_crop(image, check)
    ms = (time.monotonic() - started) * 1000
    print(f"\n[{llm.verify_model()}] {check}: {verdict} in {ms:.0f} ms")
    assert verdict.reason not in ("verification unavailable", "verification timed out", "verification busy")
    assert ms < 4500
