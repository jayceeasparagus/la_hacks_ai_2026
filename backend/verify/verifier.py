"""verify_crop(): one crop + a yes/no visual question -> Verdict. Fast, never raises, never retries."""

import base64
import hashlib
import logging
import threading
import time
from collections import OrderedDict
from typing import Literal

import cv2
import numpy as np
from pydantic import BaseModel, Field

from policy import llm
from policy.contracts import Verdict
from policy.draft import structured_output_schema
from verify import ratelimit
from verify.prompts import QUESTIONS

log = logging.getLogger("policylens.verify")

Check = Literal["transparent_bag", "professional_camera", "hard_hat", "safety_vest", "person_down"]

MIN_SIDE_PX = 40
MAX_SIDE_PX = 512
JPEG_QUALITY = 85
CONFIDENCE_THRESHOLD = 0.55  # below this a yes/no becomes "unclear"; tuned with verify.eval
TIMEOUT_S = 4.0              # total budget per call, including waiting for the rate limiter
BUSY_WAIT_S = 1.0
CACHE_SIZE = 256
MAX_REASON_WORDS = 15


class VisionAnswer(BaseModel):
    answer: Literal["yes", "no", "unclear"] = Field(description="yes, no, or unclear if you cannot tell")
    confidence: float = Field(ge=0, le=1, description="How sure you are, 0 to 1")
    reason: str = Field(description="Under 15 words, what you saw")


def verify_crop(crop: np.ndarray, check: Check) -> Verdict:
    return verify_crop_detailed(crop, check)[0]


def verify_crop_detailed(crop: np.ndarray, check: Check) -> tuple[Verdict, VisionAnswer | None]:
    """The Verdict plus the raw model answer (None when no model answer was used). For eval."""
    started = time.monotonic()
    cache_hit = False
    try:
        verdict, raw, cache_hit = _verify(crop, check, started)
    except Exception as exc:
        log.warning("verification failed: %s", exc)
        verdict, raw = Verdict(answer=None, confidence=0, reason="verification unavailable"), None
    log.info("verify check=%s latency_ms=%d answer=%s confidence=%.2f cache_hit=%s",
             check, (time.monotonic() - started) * 1000, verdict.answer, verdict.confidence, cache_hit)
    return verdict, raw


def _verify(crop, check, started) -> tuple[Verdict, VisionAnswer | None, bool]:
    if check not in QUESTIONS:
        return Verdict(answer=None, confidence=0, reason=f"unknown check {check}"), None, False
    if not isinstance(crop, np.ndarray) or crop.ndim not in (2, 3) or min(crop.shape[:2]) < MIN_SIDE_PX:
        return Verdict(answer=None, confidence=0, reason="object too small to judge"), None, False

    jpeg = encode_jpeg(crop)
    key = (check, hashlib.sha1(jpeg).hexdigest())
    cached = _cache.get(key)
    if cached is not None:
        return to_verdict(cached), cached, True

    if llm.fake_mode():
        raw = _fake_answer(crop, check)
    else:
        if not llm.available():
            return Verdict(answer=None, confidence=0, reason="verification unavailable"), None, False
        if not ratelimit.LIMITER.acquire(BUSY_WAIT_S):
            return Verdict(answer=None, confidence=0, reason="verification busy"), None, False
        remaining = max(0.1, TIMEOUT_S - (time.monotonic() - started))
        contents = [
            {"type": "text", "text": QUESTIONS[check]},
            {"type": "image", "data": base64.b64encode(jpeg).decode(), "mime_type": "image/jpeg"},
        ]
        try:
            future = llm.submit_structured(contents, structured_output_schema(VisionAnswer), model=llm.verify_model(),
                                           timeout=remaining, thinking_level="minimal")
        except Exception:
            ratelimit.LIMITER.release()
            raise
        # The slot is freed when the request really ends, even if we stopped waiting for it.
        future.add_done_callback(lambda _: ratelimit.LIMITER.release())
        try:
            text = future.result(timeout=remaining)
        except TimeoutError:
            return Verdict(answer=None, confidence=0, reason="verification timed out"), None, False
        raw = VisionAnswer.model_validate_json(text)

    _cache.put(key, raw)
    return to_verdict(raw), raw, False


def to_verdict(raw: VisionAnswer, threshold: float = CONFIDENCE_THRESHOLD) -> Verdict:
    answer = {"yes": True, "no": False}.get(raw.answer)
    confidence = min(max(raw.confidence, 0.0), 1.0)
    if answer is not None and confidence < threshold:
        answer = None
    words = raw.reason.split()
    reason = " ".join(words[:MAX_REASON_WORDS]) or "no reason given"
    return Verdict(answer=answer, confidence=confidence, reason=reason)


def encode_jpeg(crop: np.ndarray) -> bytes:
    """Longer side at most MAX_SIDE_PX, JPEG quality 85. cv2 expects BGR, which is what we get."""
    image = crop if crop.dtype == np.uint8 else np.clip(crop, 0, 255).astype(np.uint8)
    height, width = image.shape[:2]
    scale = MAX_SIDE_PX / max(height, width)
    if scale < 1:
        image = cv2.resize(image, (max(1, round(width * scale)), max(1, round(height * scale))),
                           interpolation=cv2.INTER_AREA)
    ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise ValueError("could not encode crop as JPEG")
    return buffer.tobytes()


def _fake_answer(crop: np.ndarray, check: str) -> VisionAnswer:
    """Deterministic offline verdicts so engine tests never hit the network: bright crops are
    clear bags, dark crops are professional cameras, wide crops are people lying down, a bright
    top quarter is a hard hat and a bright middle half is a safety vest."""
    brightness = float(crop.mean())
    height = crop.shape[0]
    if check in ("hard_hat", "safety_vest"):
        region = crop[: max(1, height // 4)] if check == "hard_hat" else crop[height // 4: max(height // 4 + 1, 3 * height // 4)]
        region_brightness = float(region.mean())
        answer = "yes" if region_brightness >= 128 else "no"
        return VisionAnswer(answer=answer, confidence=0.9,
                            reason=f"offline fake verdict (region brightness {region_brightness:.0f})")
    if check == "person_down":
        height, width = crop.shape[:2]
        answer = "yes" if width > 1.2 * height else "no"
        return VisionAnswer(answer=answer, confidence=0.9, reason=f"offline fake verdict (box {width}x{height})")
    if check == "transparent_bag":
        answer = "yes" if brightness >= 128 else "no"
    else:
        answer = "yes" if brightness < 100 else "no"
    return VisionAnswer(answer=answer, confidence=0.9, reason=f"offline fake verdict (brightness {brightness:.0f})")


class _LRU:
    def __init__(self, size: int):
        self.size = size
        self._items: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            if key not in self._items:
                return None
            self._items.move_to_end(key)
            return self._items[key]

    def put(self, key, value) -> None:
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self.size:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


_cache = _LRU(CACHE_SIZE)
