import os

import pytest
from dotenv import load_dotenv

from policy import llm
from verify import ratelimit, verifier

load_dotenv()


def pytest_configure(config):
    config.addinivalue_line("markers", "live: calls the real Gemini API (run with -m live; needs GEMINI_API_KEY)")


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
        if not os.getenv("GEMINI_API_KEY"):
            pytest.skip("GEMINI_API_KEY is not set")
        monkeypatch.delenv("POLICYLENS_FAKE_LLM", raising=False)
    else:
        monkeypatch.setenv("POLICYLENS_FAKE_LLM", "1")
