import os

import pytest
from dotenv import load_dotenv

from policy import llm
from verify import ratelimit, verifier

load_dotenv()


OFFLINE_CLEARED = ("GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_API_KEY", "GEMINI_API_KEY", "GEMINI_MODEL",
                   "GEMINI_VERIFY_MODEL", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION")

def pytest_configure(config):
    config.addinivalue_line("markers", "live: calls the real Gemini API (run with -m live; needs Gemini credentials)")


def pytest_collection_modifyitems(config, items):
    if "live" in (config.getoption("-m") or ""):
        return
    skip = pytest.mark.skip(reason="live Gemini test; run with -m live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def isolated(request, monkeypatch):
    """Offline FAKE mode, an empty cache and a fresh rate limiter for every non-live test."""
    verifier._cache.clear()
    llm.reset_breaker()
    monkeypatch.setattr(ratelimit, "LIMITER", ratelimit.RateLimiter())
    if "live" in request.keywords:
        if not llm.credentials_configured():
            pytest.skip("no Gemini credentials (GEMINI_API_KEY, or GOOGLE_API_KEY with Vertex AI)")
        monkeypatch.delenv("POLICYLENS_FAKE_LLM", raising=False)
    else:
        monkeypatch.setenv("POLICYLENS_FAKE_LLM", "1")
        # A developer .env (Vertex mode, model names, keys) must not change offline tests;
        # tests that need a mode set it themselves.
        for name in OFFLINE_CLEARED:
            monkeypatch.delenv(name, raising=False)
