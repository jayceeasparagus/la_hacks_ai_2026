"""Evidence images and short clips, written off the frame loop.

`submit` returns at once with evidence 'pending' so the alert can be stored and
broadcast before encoding finishes; a worker thread then writes `<name>.jpg`
(and `<name>.mp4` when frames are available) and reports the completed alert
through `on_done`. Files are written under a temporary name and renamed, so a
half-written file is never served.
"""

import hashlib
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from app.models import Alert

FILENAME = re.compile(r'^[A-Za-z0-9_-]+\.(jpg|mp4)$')
FONT = cv2.FONT_HERSHEY_SIMPLEX
REVIEW_COLOR = (0, 170, 255)  # BGR, same as vision.annotate
URGENT_COLOR = (40, 40, 230)
CODECS = ('avc1', 'mp4v')  # H.264 plays in browsers; mp4v is the fallback
MIN_FPS, MAX_FPS = 5.0, 30.0
JPEG_QUALITY = 90
log = logging.getLogger(__name__)


def safe_name(alert_id: str) -> str:
    """Deterministic, filesystem-safe and unique per alert id."""
    slug = re.sub(r'[^A-Za-z0-9_-]+', '-', alert_id).strip('-')[:40] or 'alert'
    digest = hashlib.sha1(alert_id.encode('utf-8')).hexdigest()[:12]
    return f'{slug}_{digest}'


def _bgr(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.ndim == 3 and image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    return image


def _label(image: np.ndarray, text: str, x: int, y: int, color) -> int:
    """Filled label whose bottom-left corner is (x, y), kept on screen; returns its height."""
    (tw, th), base = cv2.getTextSize(text, FONT, 0.5, 1)
    x = max(0, min(x, image.shape[1] - tw - 8))
    y = max(th + base + 4, min(y, image.shape[0]))
    cv2.rectangle(image, (x, y - th - base - 4), (x + tw + 8, y), color, -1)
    cv2.putText(image, text, (x + 4, y - base - 2), FONT, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return th + base + 4


def annotate_alert(frame: np.ndarray, alert: Alert, snapshot_ts: float | None = None) -> np.ndarray:
    """A copy of the frame with the alert's box, title and '<class> #<id>' tag.

    Drawn here rather than with vision.annotate so app/ does not depend on vision/;
    the colors match its overlay (BGR).
    """
    out = np.ascontiguousarray(_bgr(frame), dtype=np.uint8).copy()
    h, w = out.shape[:2]
    color = URGENT_COLOR if alert.severity == 'urgent' else REVIEW_COLOR
    x1, y1, x2, y2 = alert.bbox
    p1, p2 = (int(x1 * w), int(y1 * h)), (int(x2 * w), int(y2 * h))
    cv2.rectangle(out, p1, p2, color, 2, cv2.LINE_AA)
    height = _label(out, alert.title, p1[0], p1[1], color)
    source_ts = alert.ts if snapshot_ts is None else snapshot_ts
    tag = f'{alert.camera_id} | source {source_ts:.2f}s | {alert.object_class} #{alert.track_id}'
    _label(out, tag, p1[0], max(p1[1], height) + height, (60, 60, 60))
    return out


def _resampled(frames: list[tuple[float, np.ndarray]]) -> tuple[list[np.ndarray], float]:
    """Frames at a constant fps (clamped 5..30) that keep the source's real timing."""
    span = frames[-1][0] - frames[0][0]
    if span <= 0:
        return [image for _, image in frames], 10.0
    fps = min(MAX_FPS, max(MIN_FPS, (len(frames) - 1) / span))
    out, current = [], 0
    for tick in range(int(span * fps + 1e-6) + 1):
        t = frames[0][0] + tick / fps
        while current + 1 < len(frames) and frames[current + 1][0] <= t + 1e-6:
            current += 1
        out.append(frames[current][1])
    return out, fps


class EvidenceWriter:
    def __init__(self, directory: Path, max_workers: int = 2, clip_seconds: float = 4.0, max_pending: int = 4):
        if min(max_workers, max_pending, clip_seconds) <= 0:
            raise ValueError("Evidence limits must be positive")
        self._slots = threading.BoundedSemaphore(max_pending)
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.clip_seconds = clip_seconds
        self.codec: str | None = None  # fourcc that last opened successfully
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='evidence')

    def submit(self, alert: Alert, frame: np.ndarray | None, recent: list[tuple[float, np.ndarray]] | None,
               on_done: Callable[[Alert], None], *, snapshot_ts: float | None = None) -> Alert:
        """Return the alert to store and broadcast right away: evidence_status 'pending' if frame is not None,
        else 'unavailable' (and on_done is never called). In the background write <name>.jpg (the frame with the
        alert bbox, a label with alert.title and object_class drawn) and, if `recent` has >= 2 frames, <name>.mp4
        from the last clip_seconds of them; then call on_done(updated alert) with evidence_status 'ready',
        evidence_image_url '/evidence/<name>.jpg', evidence_clip_url '/evidence/<name>.mp4' or None.
        Any failure -> on_done(alert with evidence_status 'unavailable'). Never raise from submit or the worker.
        """
        unavailable = alert.model_copy(update={'evidence_status': 'unavailable',
                                               'evidence_image_url': None, 'evidence_clip_url': None})
        if frame is None or not self._slots.acquire(blocking=False):
            return unavailable
        pending = alert.model_copy(update={'evidence_status': 'pending',
                                           'evidence_image_url': None, 'evidence_clip_url': None})
        try:
            future = self._pool.submit(self._work, pending, np.array(frame, copy=True), list(recent or []), on_done, snapshot_ts)
            future.add_done_callback(lambda _: self._slots.release())
        except Exception:
            self._slots.release()
            log.exception('Evidence for %s could not be queued', alert.id)
            return unavailable
        return pending

    def _work(self, alert: Alert, frame: np.ndarray, recent: list, on_done, snapshot_ts=None) -> None:
        try:
            name = safe_name(alert.id)
            self._write_image(name, annotate_alert(frame, alert, snapshot_ts))
            clip_url = None
            if len(recent) >= 2:
                try:
                    if self._write_clip(name, recent):
                        clip_url = f'/evidence/{name}.mp4'
                except Exception:
                    log.exception('Evidence clip for %s failed; keeping the image', alert.id)
            result = alert.model_copy(update={'evidence_status': 'ready',
                                              'evidence_image_url': f'/evidence/{name}.jpg',
                                              'evidence_clip_url': clip_url})
        except Exception:
            log.exception('Evidence for %s failed', alert.id)
            result = alert.model_copy(update={'evidence_status': 'unavailable',
                                              'evidence_image_url': None, 'evidence_clip_url': None})
        try:
            on_done(result)
        except Exception:
            log.exception('Evidence callback for %s failed', alert.id)

    def _write_image(self, name: str, image: np.ndarray) -> None:
        temp, final = self.directory / f'{name}.tmp.jpg', self.directory / f'{name}.jpg'
        try:
            if not cv2.imwrite(str(temp), image, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]):
                raise OSError(f'Could not encode {final.name}')
            os.replace(temp, final)
        finally:
            temp.unlink(missing_ok=True)

    def _write_clip(self, name: str, recent: list[tuple[float, np.ndarray]]) -> bool:
        frames = sorted(((float(ts), image) for ts, image in recent if image is not None),
                        key=lambda item: item[0])
        if len(frames) < 2:
            return False
        newest = frames[-1][0]
        frames = [item for item in frames if newest - item[0] <= self.clip_seconds]
        if len(frames) < 2:
            return False
        h, w = frames[0][1].shape[:2]
        size = (w - w % 2, h - h % 2)  # H.264 needs even dimensions
        images, fps = _resampled(frames)
        temp, final = self.directory / f'{name}.tmp.mp4', self.directory / f'{name}.mp4'
        writer = None
        try:
            for codec in CODECS:
                writer = cv2.VideoWriter(str(temp), cv2.VideoWriter_fourcc(*codec), fps, size)
                if writer.isOpened():
                    self.codec = codec
                    break
                writer.release()
                writer = None
            if writer is None:
                return False
            for image in images:
                image = _bgr(image)
                if (image.shape[1], image.shape[0]) != size:
                    image = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
                writer.write(np.ascontiguousarray(image, dtype=np.uint8))
            writer.release()
            writer = None
            if not temp.exists() or temp.stat().st_size == 0:
                return False
            os.replace(temp, final)
            return True
        finally:
            if writer is not None:
                writer.release()
            temp.unlink(missing_ok=True)

    def resolve(self, filename: str) -> Path | None:
        """The evidence file for a generated basename, or None (no path traversal)."""
        if not isinstance(filename, str) or not FILENAME.fullmatch(filename):
            return None
        root = self.directory.resolve()
        path = (root / filename).resolve()
        if path.parent != root or not path.is_file():
            return None
        return path

    def shutdown(self, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait)
