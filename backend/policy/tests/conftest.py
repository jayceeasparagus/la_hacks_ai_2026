import os

import pytest
from dotenv import load_dotenv

from policy import cache, llm

load_dotenv()


def pytest_configure(config):
    config.addinivalue_line("markers", "live: calls the real Gemini API (run with -m live; needs GEMINI_API_KEY)")


def pytest_collection_modifyitems(config, items):
    # Live tests run only when asked for with -m live.
    if "live" in (config.getoption("-m") or ""):
        return
    skip = pytest.mark.skip(reason="live Gemini test; run with -m live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def isolated(request, monkeypatch, tmp_path):
    """Offline FAKE mode and a throwaway cache for every non-live test."""
    monkeypatch.setenv("POLICYLENS_CACHE_DIR", str(tmp_path / "cache"))
    cache.clear_memory()
    llm.reset_breaker()
    if "live" in request.keywords:
        if not os.getenv("GEMINI_API_KEY"):
            pytest.skip("GEMINI_API_KEY is not set")
        monkeypatch.delenv("POLICYLENS_FAKE_LLM", raising=False)
    else:
        monkeypatch.setenv("POLICYLENS_FAKE_LLM", "1")
