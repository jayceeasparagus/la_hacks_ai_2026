"""Thin Gemini wrapper (google-genai Interactions API): structured JSON calls with hard timeouts.

FAKE mode (env POLICYLENS_FAKE_LLM=1) is checked by callers, which then skip the network.
"""

import logging
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor

log = logging.getLogger("policylens.llm")

DEFAULT_MODEL = "gemini-flash-latest"

# Circuit breaker: after this many failures in a row, skip Gemini for a while so a dead network
# (venue Wi-Fi, bad key, quota) costs nothing instead of a timeout on every call.
FAILURES_TO_PAUSE = 3
PAUSE_SECONDS = 30.0


class GeminiUnavailable(RuntimeError):
    pass


_breaker_lock = threading.Lock()
_failures = 0
_paused_until = 0.0

_client = None
_client_lock = threading.Lock()
# Calls run here so callers can enforce a wall-clock timeout with future.result(timeout=...).
_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="gemini")


def fake_mode() -> bool:
    return os.getenv("POLICYLENS_FAKE_LLM", "").strip().lower() in ("1", "true", "yes")


def policy_model() -> str:
    return os.getenv("GEMINI_MODEL") or DEFAULT_MODEL


def verify_model() -> str:
    return os.getenv("GEMINI_VERIFY_MODEL") or os.getenv("GEMINI_MODEL") or DEFAULT_MODEL


def get_client():
    """One shared client. Reads GEMINI_API_KEY from the environment. SDK retries are off:
    the compiler retries once itself, and the verifier must never retry."""
    global _client
    with _client_lock:
        if _client is None:
            from google import genai
            from google.genai import types

            _client = genai.Client(http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)))
        return _client


def submit_structured(
    contents,
    schema: dict,
    *,
    model: str,
    timeout: float,
    system: str | None = None,
    thinking_level: str | None = None,
) -> Future:
    """Start a structured-output call in the worker pool; the future resolves to the JSON text.
    While the breaker is open the future fails at once with GeminiUnavailable."""
    if not available():
        future: Future = Future()
        future.set_exception(GeminiUnavailable("Gemini paused after repeated failures"))
        return future

    def call() -> str:
        started = time.monotonic()
        kwargs = {
            "model": model,
            "input": contents,
            "response_format": {"type": "text", "mime_type": "application/json", "schema": schema},
            "timeout": timeout,
        }
        if system:
            kwargs["system_instruction"] = system
        if thinking_level:
            kwargs["generation_config"] = {"thinking_level": thinking_level}
        try:
            interaction = get_client().interactions.create(**kwargs)
        except Exception as exc:
            log.warning("Gemini call failed after %d ms (%s): %s", _ms(started), model, exc)
            _record(ok=False, error=exc)
            raise
        _record(ok=True)
        text = strip_fences(interaction.output_text or "")
        log.info("Gemini %s answered in %d ms", model, _ms(started))
        if not text:
            raise ValueError("Gemini returned no text")
        return text

    return _pool.submit(call)


def call_structured(contents, schema: dict, *, model: str, timeout: float, system: str | None = None,
                    thinking_level: str | None = None) -> str:
    """Blocking structured call. Raises TimeoutError after `timeout` seconds, or the API error."""
    future = submit_structured(contents, schema, model=model, timeout=timeout, system=system,
                               thinking_level=thinking_level)
    return future.result(timeout=timeout)


def strip_fences(text: str) -> str:
    """Structured output should be bare JSON, but tolerate a ```json fence around it."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def available() -> bool:
    with _breaker_lock:
        return time.monotonic() >= _paused_until


def reset_breaker() -> None:
    global _failures, _paused_until
    with _breaker_lock:
        _failures, _paused_until = 0, 0.0


def _record(ok: bool, error: Exception | None = None) -> None:
    global _failures, _paused_until
    with _breaker_lock:
        if ok:
            _failures = 0
            return
        _failures += 1
        if _failures >= FAILURES_TO_PAUSE:
            _paused_until = time.monotonic() + PAUSE_SECONDS
            _failures = 0
            log.error("Gemini paused for %.0f s after %d failures in a row (last: %s); using fallbacks",
                      PAUSE_SECONDS, FAILURES_TO_PAUSE, error)


def status() -> dict:
    """For a health endpoint: which models, whether a key is set, whether Gemini is paused."""
    return {
        "mode": "fake" if fake_mode() else "gemini",
        "policy_model": policy_model(),
        "verify_model": verify_model(),
        "api_key_set": bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
        "available": available(),
    }


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
