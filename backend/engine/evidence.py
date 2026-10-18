"""Bounded source-frame buffering and asynchronous JPEG/MP4 evidence writing."""

from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import logging
from math import ceil
import os
from pathlib import Path
import threading
import time
from uuid import uuid4

import cv2

from app.models import Alert
from engine.images import valid_image

log = logging.getLogger('policylens.engine.evidence')


class FrameBuffer:
    """Camera-worker-owned ring: at most 10 Hz, 640 px wide, 32 MiB by default.

    Arrays are owned and read-only, so snapshot lists can safely share them with
    writers while old frames are evicted. Time and byte limits both apply.
    """

    def __init__(self, seconds=4.2, max_bytes=32 * 1024 * 1024,
                 max_width=640, sample_fps=10):
        if min(seconds, max_bytes, max_width, sample_fps) <= 0:
            raise ValueError('Buffer limits must be positive')
        self.seconds, self.max_bytes = seconds, max_bytes
        self.max_width, self.sample_interval = max_width, 1 / sample_fps
        self._frames = deque()
        self.byte_size = 0
        self._last_sample = None

    def remember(self, image, ts):
        while self._frames and ts - self._frames[0][0] > self.seconds:
            self.byte_size -= self._frames.popleft()[1].nbytes
        if not valid_image(image):
            return
        if self._last_sample is not None and ts - self._last_sample < self.sample_interval - 1e-9:
            return
        height, width = image.shape[:2]
        sample = (cv2.resize(image, (self.max_width, max(1, round(height * self.max_width / width))))
                  if width > self.max_width else image.copy())
        if sample.nbytes > self.max_bytes:
            return
        sample.setflags(write=False)
        self._frames.append((ts, sample))
        self.byte_size += sample.nbytes
        self._last_sample = ts
        while self.byte_size > self.max_bytes:
            self.byte_size -= self._frames.popleft()[1].nbytes

    def snapshot(self, end_ts, seconds=4):
        return [(ts, image) for ts, image in self._frames if end_ts - seconds - 0.1 <= ts <= end_ts]

    def clear(self):
        self._frames.clear()
        self.byte_size = 0
        self._last_sample = None


@dataclass(frozen=True)
class EvidenceResult:
    alert_id: str
    camera_id: str
    status: str
    image_url: str | None = None
    clip_url: str | None = None
    error: str | None = None

    def apply(self, current: Alert) -> Alert:
        """Merge ONLY evidence fields into the latest stored/reviewed alert."""
        if current.id != self.alert_id or current.camera_id != self.camera_id:
            raise ValueError('Evidence belongs to another alert')
        data = current.model_dump()
        data.update(evidence_status=self.status, evidence_image_url=self.image_url,
                    evidence_clip_url=self.clip_url)
        return Alert.model_validate(data)


@dataclass
class EvidenceTicket:
    future: Future
    alert_id: str
    camera_id: str


class EvidenceWriter:
    """Encoding and file I/O happen in a separate, bounded worker pool.

    A ready result can contain only a JPEG if no clip is possible. Generated
    basenames are independent of camera/alert text; files become visible only
    after atomic renames. HTTP serving is a later application-layer task.
    """

    def __init__(self, directory: Path, *, max_workers=1, max_pending=4, clip_fps=10):
        if min(max_workers, max_pending, clip_fps) <= 0:
            raise ValueError('Writer limits must be positive')
        self.directory = Path(directory)
        self.clip_fps = clip_fps
        self._executor = ThreadPoolExecutor(max_workers=max_workers,
                                            thread_name_prefix='policy-evidence')
        self._slots = threading.BoundedSemaphore(max_pending)
        self._lock = threading.Lock()
        self._closed = False

    def submit(self, alert: Alert, image, frames, *, snapshot_ts: float) -> EvidenceTicket | None:
        with self._lock:
            if self._closed or not valid_image(image) or not self._slots.acquire(blocking=False):
                return None
            try:
                future = self._executor.submit(self._write, alert.model_copy(deep=True),
                    image.copy(), list(frames), snapshot_ts)
            except Exception:
                self._slots.release()
                raise
            future.add_done_callback(lambda _: self._slots.release())
            return EvidenceTicket(future, alert.id, alert.camera_id)

    def poll(self, ticket: EvidenceTicket) -> EvidenceResult | None:
        if not ticket.future.done():
            return None
        if ticket.future.cancelled():
            return EvidenceResult(ticket.alert_id, ticket.camera_id, 'unavailable',
                                  error='evidence job cancelled')
        return ticket.future.result()

    @staticmethod
    def _label(image, text):
        cv2.putText(image, text, (8, min(22, image.shape[0] - 1)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 2, cv2.LINE_AA)

    def _write(self, alert, image, frames, snapshot_ts):
        started = time.monotonic()
        basename = uuid4().hex
        jpeg = self.directory / f'{basename}.jpg'
        jpeg_temp = self.directory / f'{basename}.jpg.part'
        video = self.directory / f'{basename}.mp4'
        video_temp = self.directory / f'{basename}.part.mp4'
        image_url, clip_url, error = None, None, None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            height, width = image.shape[:2]
            x1, y1, x2, y2 = alert.bbox
            cv2.rectangle(image, (round(x1 * (width - 1)), round(y1 * (height - 1))),
                          (round(x2 * (width - 1)), round(y2 * (height - 1))), (0, 0, 255), 2)
            self._label(image, f'{alert.camera_id} | source {snapshot_ts:.2f}s')
            ok, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if not ok:
                raise ValueError('JPEG encoder unavailable')
            jpeg_temp.write_bytes(encoded.tobytes())
            os.replace(jpeg_temp, jpeg)
            image_url = f'/evidence/{jpeg.name}'
            usable = [(ts, sample) for ts, sample in frames
                      if valid_image(sample) and alert.ts - 4.1 <= ts <= alert.ts]
            usable.sort(key=lambda item: item[0])
            if len(usable) >= 2 and usable[-1][0] > usable[0][0]:
                try:
                    self._write_clip(video_temp, usable, alert)
                    os.replace(video_temp, video)
                    clip_url = f'/evidence/{video.name}'
                except Exception:
                    # Preserve a valid snapshot when the codec is unavailable.
                    error = 'clip encoding unavailable; snapshot preserved'
            else:
                error = 'insufficient buffered video; snapshot preserved'
        except Exception:
            error = 'evidence encoding unavailable'
        finally:
            for partial in (jpeg_temp, video_temp):
                try:
                    partial.unlink(missing_ok=True)
                except OSError:
                    log.warning('Evidence temporary-file cleanup failed')
        log.info('Evidence camera=%s alert=%s latency_ms=%.1f image=%s clip=%s',
                 alert.camera_id, alert.id, (time.monotonic() - started) * 1000,
                 image_url is not None, clip_url is not None)
        if error:
            log.warning('Evidence camera=%s alert=%s status=%s', alert.camera_id, alert.id, error)
        return EvidenceResult(alert.id, alert.camera_id, 'ready' if image_url else 'unavailable',
                              image_url, clip_url, error)

    def _write_clip(self, path, samples, alert):
        height, width = samples[0][1].shape[:2]
        size = (width - width % 2, height - height % 2)
        if min(size) < 2:
            raise ValueError('Frames too small for MP4')
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), self.clip_fps, size)
        try:
            if not writer.isOpened():
                raise ValueError('MP4 encoder unavailable')
            start = max(alert.ts - 4, samples[0][0])
            count = max(1, ceil((alert.ts - start) * self.clip_fps))
            index = 0
            for tick in range(count):
                ts = start + tick / self.clip_fps
                while index + 1 < len(samples) and samples[index + 1][0] <= ts:
                    index += 1
                actual_ts, sample = samples[index]
                view = cv2.resize(sample, size)
                self._label(view, f'{alert.camera_id} | source {actual_ts:.2f}s')
                writer.write(view)
        finally:
            writer.release()
        capture = cv2.VideoCapture(str(path))
        try:
            valid, decoded = capture.read()
            if not valid or decoded is None:
                raise ValueError('MP4 could not be decoded')
        finally:
            capture.release()

    def close(self, wait=True):
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=wait, cancel_futures=not wait)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
