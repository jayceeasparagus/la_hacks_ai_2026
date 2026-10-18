"""compile_policy(): plain-English policy -> validated CompileResult. Orchestration only."""

import logging
import os
import time
from dataclasses import dataclass

from policy import cache, capability, fallback, llm, prompts
from policy.contracts import CompileResult, Zone
from policy.draft import DraftPolicy, build_draft_schema

log = logging.getLogger("policylens.policy")

MAX_PROMPT_CHARS = 2000
# Total compile budget (both attempts). Measured on Vertex gemini-2.5-flash: ~12 s per cold call, so 12 s
# fell back offline about half the time. Override with POLICYLENS_COMPILE_TIMEOUT_S.
TOTAL_TIMEOUT_S = 30.0
MIN_ATTEMPT_S = 1.0


def _total_timeout() -> float:
    try:
        value = float(os.getenv("POLICYLENS_COMPILE_TIMEOUT_S", ""))
    except ValueError:
        return TOTAL_TIMEOUT_S
    return value if value > 0 else TOTAL_TIMEOUT_S

EMPTY_WARNING = "Type a policy first, for example: 'Keep the emergency exit clear for more than 5 seconds.'"
TOO_LONG_WARNING = f"That policy is long; I only read the first {MAX_PROMPT_CHARS} characters."
UNRECOGNIZED_WARNING = (
    "I couldn't turn that into rules right now. Try again, or rephrase as 'In <zone>, alert if <object> ...'."
)
NOTHING_FOUND_WARNING = (
    "I didn't find any rules I can monitor in that. Try something like "
    "'In <zone>, alert if a bag stays for more than 10 seconds.'"
)


@dataclass
class CompileInfo:
    source: str  # "gemini" | "cache" | "fallback" | "fake"
    latency_ms: int
    model: str


def compile_policy(prompt: str, zones: list[Zone]) -> CompileResult:
    """Never raises: bad input becomes warnings or unsupported entries."""
    return compile_policy_with_info(prompt, zones)[0]


def compile_policy_with_info(prompt: str, zones: list[Zone]) -> tuple[CompileResult, CompileInfo]:
    started = time.monotonic()
    model = "fake" if llm.fake_mode() else llm.policy_model()
    try:
        result, source = _compile(prompt, zones, model, started)
    except Exception:
        log.exception("compile_policy failed unexpectedly; returning an empty result")
        result, source = CompileResult(rules=[], warnings=[UNRECOGNIZED_WARNING], unsupported=[]), "fallback"
    info = CompileInfo(source=source, latency_ms=int((time.monotonic() - started) * 1000), model=model)
    log.info("compile source=%s latency_ms=%d rules=%d", info.source, info.latency_ms, len(result.rules))
    return result, info


def _compile(prompt: str, zones: list[Zone], model: str, started: float) -> tuple[CompileResult, str]:
    text = " ".join((prompt or "").split())
    notes = []
    if not text:
        return CompileResult(rules=[], warnings=[EMPTY_WARNING], unsupported=[]), "fallback"
    if len(text) > MAX_PROMPT_CHARS:
        text = text[:MAX_PROMPT_CHARS]
        notes.append(TOO_LONG_WARNING)

    if llm.fake_mode():
        return _finish(_fallback(text, zones), notes), "fake"

    key = cache.make_key(text, zones, model)
    cached = cache.get(key)
    if cached is not None:
        return _finish(cached, notes), "cache"

    try:
        draft = _ask_gemini(text, zones, model, deadline=started + _total_timeout())
        result = capability.finalize(draft, zones)
    except Exception as exc:
        log.warning("Using the deterministic fallback because Gemini compile failed: %s", exc)
        return _finish(_fallback(text, zones), notes), "fallback"

    cache.put(key, result)
    return _finish(result, notes), "gemini"


def _ask_gemini(text: str, zones: list[Zone], model: str, deadline: float) -> DraftPolicy:
    schema = build_draft_schema(zones)
    system = prompts.build_system_prompt()
    user = prompts.build_user_prompt(text, zones)
    error: Exception = TimeoutError("no time left to call Gemini")
    for attempt in (1, 2):
        remaining = deadline - time.monotonic()
        if remaining < MIN_ATTEMPT_S:
            break
        try:
            raw = llm.call_structured(user, schema, model=model, timeout=remaining, system=system)
            return DraftPolicy.model_validate_json(raw)
        except Exception as exc:
            error = exc
            log.warning("Gemini compile attempt %d failed: %s", attempt, exc)
    raise error


def _fallback(text: str, zones: list[Zone]) -> CompileResult:
    draft = fallback.compile_fallback(text, zones)
    if draft is None:
        log.info("Fallback did not recognize the policy")
        return CompileResult(rules=[], warnings=[UNRECOGNIZED_WARNING], unsupported=[])
    log.info("Fallback compiled %d rules", len(draft.rules))
    return capability.finalize(draft, zones)


def _finish(result: CompileResult, notes: list[str]) -> CompileResult:
    warnings = notes + result.warnings
    if not result.rules and not result.unsupported and not warnings:
        warnings.append(NOTHING_FOUND_WARNING)
    return CompileResult(rules=result.rules, warnings=list(dict.fromkeys(warnings)), unsupported=result.unsupported)
