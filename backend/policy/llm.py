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
    """Start a structured-output call in the worker pool; the future resolves to the JSON text."""

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
            raise
        text = interaction.output_text
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


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
