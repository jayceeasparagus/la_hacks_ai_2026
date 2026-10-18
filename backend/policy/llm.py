"""Thin Gemini wrapper: structured JSON calls with hard timeouts.

Gemini Developer API keys use the Interactions API. Vertex AI (GOOGLE_GENAI_USE_VERTEXAI=true, with an
express-mode API key or gcloud credentials) does not serve /interactions (404), so Vertex calls go
through models.generate_content with the same schema, system prompt and image parts.

FAKE mode (env POLICYLENS_FAKE_LLM=1) is checked by callers, which then skip the network.
"""

import logging
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor

log = logging.getLogger("policylens.llm")

DEFAULT_MODEL = "gemini-flash-latest"
DEFAULT_VERTEX_MODEL = "gemini-2.5-flash"  # Vertex has no "-latest" aliases
# Vertex express keys default to the global endpoint, which took ~11 s on a new or idle connection
# (2026-10-18); us-central1 answered in ~0.75 s. POLICYLENS_VERTEX_LOCATION=global restores global.
DEFAULT_VERTEX_LOCATION = "us-central1"

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


def vertex_mode() -> bool:
    return os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower() in ("1", "true", "yes")


def _default_model() -> str:
    return DEFAULT_VERTEX_MODEL if vertex_mode() else DEFAULT_MODEL


def policy_model() -> str:
    return os.getenv("GEMINI_MODEL") or _default_model()


def verify_model() -> str:
    return os.getenv("GEMINI_VERIFY_MODEL") or os.getenv("GEMINI_MODEL") or _default_model()


def vertex_express_base_url() -> str | None:
    """The regional endpoint for Vertex express keys, or None for the SDK's global endpoint."""
    location = (os.getenv("POLICYLENS_VERTEX_LOCATION") or DEFAULT_VERTEX_LOCATION).strip().lower()
    if not location or location == "global":
        return None
    return f"https://{location}-aiplatform.googleapis.com/"


def get_client():
    """One shared client. Reads GEMINI_API_KEY from the environment. SDK retries are off:
    the compiler retries once itself, and the verifier must never retry."""
    global _client
    with _client_lock:
        if _client is None:
            if not credentials_configured():
                # Don't let the SDK fail halfway through its constructor: the half-built client's
                # cleanup later logs "Task exception was never retrieved" on the server's event loop.
                raise GeminiUnavailable('GEMINI_API_KEY is not set')
            from google import genai

            key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
            if vertex_mode() and key:
                # Vertex AI express mode: an API key instead of a project and gcloud credentials.
                _client = genai.Client(vertexai=True, api_key=key,
                                       http_options=http_options(vertex_express_base_url()))
            else:
                _client = genai.Client(http_options=http_options())
        return _client


def credentials_configured() -> bool:
    """An API key, or Vertex AI mode (which authenticates with Google Cloud credentials)."""
    return bool(os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY') or vertex_mode())


def http_options(base_url: str | None = None):
    from google.genai import types

    # attempts=0, not 1: the Interactions client maps attempts straight to max_retries, so 1 would
    # still retry once on 429/5xx (checked in google-genai 2.31.0).
    return types.HttpOptions(base_url=base_url, retry_options=types.HttpRetryOptions(attempts=0))


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
        if vertex_mode():
            try:
                text = _generate_content(contents, schema, model=model, timeout=timeout, system=system,
                                         thinking_level=thinking_level)
            except Exception as exc:
                log.warning("Gemini (Vertex) call failed after %d ms (%s): %s", _ms(started), model, exc)
                _record(ok=False, error=exc)
                raise
            _record(ok=True)
            log.info("Gemini (Vertex) %s answered in %d ms", model, _ms(started))
            if not text:
                raise ValueError("Gemini returned no text")
            return text
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


def _generate_content(contents, schema: dict, *, model: str, timeout: float, system: str | None,
                      thinking_level: str | None) -> str:
    """The Vertex AI path: models.generate_content with JSON-schema output."""
    import base64

    from google.genai import types

    if isinstance(contents, str):
        parts = contents
    else:
        parts = []
        for part in contents:
            if part.get("type") == "image":
                parts.append(types.Part.from_bytes(data=base64.b64decode(part["data"]), mime_type=part["mime_type"]))
            else:
                parts.append(types.Part.from_text(text=part["text"]))
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema=schema,
        system_instruction=system or None,
        http_options=types.HttpOptions(timeout=int(timeout * 1000)),
    )
    if thinking_level:
        # Gemini 2.5 models turn thinking off with a zero budget; newer models take a level.
        config.thinking_config = (types.ThinkingConfig(thinking_budget=0) if "2.5" in model and thinking_level == "minimal"
                                  else types.ThinkingConfig(thinking_level=thinking_level))
    response = get_client().models.generate_content(model=model, contents=parts, config=config)
    return strip_fences(response.text or "")


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
        "mode": "fake" if fake_mode() else ("vertex" if vertex_mode() else "gemini"),
        "endpoint": (vertex_express_base_url() or "global") if vertex_mode() else "gemini",
        "policy_model": policy_model(),
        "verify_model": verify_model(),
        "api_key_set": credentials_configured(),
        "available": available(),
    }


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
