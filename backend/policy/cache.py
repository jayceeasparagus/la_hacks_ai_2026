"""Compile cache, in memory and on disk, so a known prompt compiles instantly even offline."""

import hashlib
import json
import logging
import os
import threading
from pathlib import Path

from policy.contracts import CompileResult, Zone

log = logging.getLogger("policylens.policy")

DEFAULT_DIR = Path(__file__).parent / ".cache"

_memory: dict[str, CompileResult] = {}
_lock = threading.Lock()


def cache_dir() -> Path:
    return Path(os.getenv("POLICYLENS_CACHE_DIR") or DEFAULT_DIR)


def make_key(prompt: str, zones: list[Zone], model: str) -> str:
    payload = json.dumps(
        {"prompt": prompt, "zones": [z.model_dump() for z in zones], "model": model}, sort_keys=True
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def get(key: str) -> CompileResult | None:
    with _lock:
        if key in _memory:
            return _memory[key].model_copy(deep=True)
    path = cache_dir() / f"{key}.json"
    try:
        result = CompileResult.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception as exc:
        log.warning("Ignoring unreadable cache file %s: %s", path.name, exc)
        return None
    with _lock:
        _memory[key] = result
    return result.model_copy(deep=True)


def put(key: str, result: CompileResult) -> None:
    with _lock:
        _memory[key] = result.model_copy(deep=True)
    try:
        folder = cache_dir()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{key}.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    except OSError as exc:
        log.warning("Could not write compile cache: %s", exc)


def clear_memory() -> None:
    with _lock:
        _memory.clear()
