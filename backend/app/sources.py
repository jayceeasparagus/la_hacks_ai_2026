"""Camera sources behind one small interface for the camera workers.

Every source has `frames()` (an iterator of (BGR image, TrackFrame or Person 1's
draft)), `recent_frames(seconds)` (evidence frames as (ts, image), oldest first),
`status` ('connecting' | 'online' | 'offline'), `fps`, `error`, `ended` (True once
the source finished for good) and `stop()`.

Source strings:
- `webcam:N`, `url:...`, `clip:path` -> Person 1's vision.pipeline.VisionPipeline
  (imported lazily, so the server runs without ultralytics).
- `synthetic:<scenario>` -> engine.fake_tracks scenarios or the local entrance
  scenes below, rendered as images and looped forever at real speed.
- `replay:<tracks.jsonl>` -> approved TrackFrame JSONL at real speed; ends after the file.

Errors never contain the source string: camera URLs may carry credentials.
`POLICYLENS_SOURCE_SPEED` multiplies playback speed of synthetic and replay sources.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Iterator, Protocol

import cv2
import numpy as np

from app.models import Camera, Track, TrackFrame
from app.render import WIDTH, render_scene

log = logging.getLogger(__name__)

VISION_MISSING = 'vision pipeline not installed (merge person1/vision and install its requirements)'
UNSUPPORTED = 'unsupported camera source; use webcam:N, url:..., clip:path, synthetic:<scenario> or replay:<file>'
TRACK_ID_STRIDE = 1000  # synthetic loops offset track ids so each loop is a new object
SNAPSHOT_TIMEOUT = 3.0


class Source(Protocol):
    camera_id: str
    status: str
    fps: float
    error: str | None
    ended: bool

    def frames(self) -> Iterator[tuple[np.ndarray, object]]: ...
    def recent_frames(self, seconds: float) -> list[tuple[float, np.ndarray]]: ...
    def stop(self) -> None: ...


class SourceError(RuntimeError):
    """A source could not start; the message is safe to show users."""


def source_speed() -> float:
    try:
        speed = float(os.getenv('POLICYLENS_SOURCE_SPEED', '1') or 1)
    except ValueError:
        return 1.0
    return speed if speed > 0 else 1.0


def scheme(source: str) -> tuple[str, str]:
    kind, _, value = source.strip().partition(':')
    return kind.lower(), value


# Synthetic scenes ----------------------------------------------------------------

def _frames(camera_id: str, seconds: float, tracks_at) -> list[TrackFrame]:
    out = []
    for tick in range(int(round(seconds * 10)) + 1):
        ts = round(tick / 10, 3)
        out.append(TrackFrame(camera_id=camera_id, ts=ts, tracks=tracks_at(ts)))
    return out


def _entrance_bag(camera_id: str) -> tuple[list[TrackFrame], frozenset[int]]:
    """A person walks in carrying an opaque backpack that stands in the entrance for ~3 s,
    then a clear bag passes through for ~3 s (the fake verifier calls it clear)."""
    def tracks(ts: float) -> list[Track]:
        out = []
        if 0.5 <= ts < 4.5:
            out.append(Track(track_id=1, object_class='person', bbox=(0.25, 0.25, 0.38, 0.85),
                             confidence=0.9))
        if 1.0 <= ts < 4.0:
            out.append(Track(track_id=2, object_class='backpack', bbox=(0.42, 0.5, 0.58, 0.8),
                             confidence=0.88))
        if 6.5 <= ts < 9.5:
            out.append(Track(track_id=3, object_class='handbag', bbox=(0.45, 0.55, 0.6, 0.82),
                             confidence=0.85))
        return out
    return _frames(camera_id, 12, tracks), frozenset({3})


def _entrance_opaque(camera_id: str) -> tuple[list[TrackFrame], frozenset[int]]:
    """Only the opaque backpack: one review alert per loop."""
    def tracks(ts: float) -> list[Track]:
        if 1.0 <= ts < 4.0:
            return [Track(track_id=2, object_class='backpack', bbox=(0.42, 0.5, 0.58, 0.8),
                          confidence=0.88)]
        return []
    return _frames(camera_id, 8, tracks), frozenset()


LOCAL_SCENES = {'entrance_bag': _entrance_bag, 'entrance_opaque': _entrance_opaque}


def synthetic_scene(name: str, camera_id: str) -> tuple[list[TrackFrame], frozenset[int]]:
    """(frames of one loop, track ids drawn as clear bags)."""
    if name in LOCAL_SCENES:
        return LOCAL_SCENES[name](camera_id)
    from engine.fake_tracks import scenario
    return scenario(name, camera_id), frozenset()


# Played sources -------------------------------------------------------------------

class _PlayedSource:
    """Shared pacing and rendering for synthetic and replay sources."""

    BUFFER_SECONDS = 10.0

    def __init__(self, camera_id: str, frames: list[TrackFrame], *, title: str,
                 clear_ids: frozenset[int] = frozenset(), loop: bool, speed: float | None = None):
        if not frames:
            raise SourceError('source has no frames')
        self.camera_id = camera_id
        self.status = 'connecting'
        self.fps = 0.0
        self.error: str | None = None
        self.ended = False
        self._frames = frames
        self._title = title
        self._clear_ids = clear_ids
        self._loop = loop
        self._speed = speed or source_speed()
        self._stop = threading.Event()
        self._recent: deque[TrackFrame] = deque()
        self._lock = threading.Lock()

    def render(self, tf: TrackFrame) -> np.ndarray:
        clear = frozenset(track.track_id for track in tf.tracks
                          if track.track_id % TRACK_ID_STRIDE in self._clear_ids)
        return render_scene(tf, f'{self.camera_id}  {self._title}', clear)

    def first_frame(self) -> np.ndarray:
        return self.render(self._frames[0])

    def frames(self) -> Iterator[tuple[np.ndarray, TrackFrame]]:
        period = self._frames[-1].ts - self._frames[0].ts + 0.1
        start = time.monotonic()
        window_start, window_count = start, 0
        loop = 0
        self.status = 'online'
        while not self._stop.is_set():
            for base in self._frames:
                offset = loop * period
                tf = base.model_copy(update={
                    'camera_id': self.camera_id,
                    'ts': round(base.ts - self._frames[0].ts + offset, 6),
                    'tracks': [track.model_copy(update={'track_id': track.track_id + loop * TRACK_ID_STRIDE})
                               for track in base.tracks] if loop else list(base.tracks),
                })
                delay = start + tf.ts / self._speed - time.monotonic()
                if delay > 0 and self._stop.wait(delay):
                    return
                if self._stop.is_set():
                    return
                with self._lock:
                    self._recent.append(tf)
                    while self._recent and tf.ts - self._recent[0].ts > self.BUFFER_SECONDS:
                        self._recent.popleft()
                window_count += 1
                now = time.monotonic()
                if now - window_start >= 1.0:
                    self.fps = window_count / (now - window_start)
                    window_start, window_count = now, 0
                yield self.render(tf), tf
            if not self._loop:
                break
            loop += 1
        if not self._stop.is_set():
            self.ended = True
            self.status, self.fps, self.error = 'offline', 0.0, 'replay ended'

    def recent_frames(self, seconds: float) -> list[tuple[float, np.ndarray]]:
        with self._lock:
            if not self._recent:
                return []
            newest = self._recent[-1].ts
            chosen = [tf for tf in self._recent if newest - tf.ts <= seconds]
        return [(tf.ts, self.render(tf)) for tf in chosen]

    def stop(self) -> None:
        self._stop.set()


class SyntheticSource(_PlayedSource):
    def __init__(self, camera_id: str, name: str, speed: float | None = None):
        try:
            frames, clear_ids = synthetic_scene(name, camera_id)
        except ValueError as error:
            raise SourceError(f'unknown synthetic scenario {name!r}') from error
        super().__init__(camera_id, frames, title=f'synthetic:{name}', clear_ids=clear_ids,
                         loop=True, speed=speed)


class ReplaySource(_PlayedSource):
    def __init__(self, camera_id: str, path: str, speed: float | None = None):
        from engine.replay import read_frames
        file = Path(path)
        if not file.is_file():
            raise SourceError('replay file not found')
        try:
            frames = [tf.model_copy(update={'camera_id': camera_id}) for tf in read_frames(file)]
        except ValueError as error:
            raise SourceError(f'invalid replay file: {error}') from error
        super().__init__(camera_id, frames, title=f'replay:{file.name}', loop=False, speed=speed)


# Vision sources --------------------------------------------------------------------

class VisionSource:
    """Person 1's VisionPipeline, built inside the worker thread (model loading is slow)."""

    STATUS = {'online': 'online', 'connecting': 'connecting', 'starting': 'connecting'}

    def __init__(self, camera_id: str, source: str, multi_camera: bool = False):
        self.camera_id = camera_id
        self.ended = False
        self._source = source
        self._multi_camera = multi_camera
        self._pipeline = None
        self._error: str | None = None
        self._stopped = False

    @property
    def status(self) -> str:
        if self._error:
            return 'offline'
        if self._pipeline is None:
            return 'connecting'
        return self.STATUS.get(self._pipeline.status, 'offline')

    @property
    def fps(self) -> float:
        return float(self._pipeline.fps) if self._pipeline is not None and self.status == 'online' else 0.0

    @property
    def error(self) -> str | None:
        if self._error:
            return self._error
        if self._pipeline is not None and self.status == 'offline':
            return 'clip ended' if self._pipeline.status == 'ended' else 'camera offline; retrying'
        return None

    def frames(self) -> Iterator[tuple[np.ndarray, object]]:
        try:
            from vision.pipeline import VisionPipeline
        except Exception as error:  # ImportError, or ultralytics/torch failing to load
            self._error = VISION_MISSING
            raise SourceError(VISION_MISSING) from error
        kind, _ = scheme(self._source)
        self._pipeline = VisionPipeline(self.camera_id, self._source, realtime=kind == 'clip',
                                        multi_camera=self._multi_camera)
        if self._stopped:
            self._pipeline.stop()
            return
        yield from self._pipeline.frames()

    def recent_frames(self, seconds: float) -> list[tuple[float, np.ndarray]]:
        return self._pipeline.recent_frames(seconds) if self._pipeline is not None else []

    def stop(self) -> None:
        self._stopped = True
        if self._pipeline is not None:
            self._pipeline.stop()


class BrokenSource:
    """A camera whose source string cannot work: offline with a safe error, no frames."""

    def __init__(self, camera_id: str, error: str):
        self.camera_id = camera_id
        self.status, self.fps, self.error, self.ended = 'offline', 0.0, error, False

    def frames(self):
        raise SourceError(self.error)

    def recent_frames(self, seconds: float):
        return []

    def stop(self) -> None:
        pass


def build_source(camera: Camera, multi_camera: bool = False):
    """The default source factory used by the camera workers. Raises SourceError."""
    kind, value = scheme(camera.source)
    if kind in ('webcam', 'url', 'clip'):
        return VisionSource(camera.id, camera.source, multi_camera=multi_camera)
    if kind == 'synthetic':
        return SyntheticSource(camera.id, value.strip())
    if kind == 'replay':
        return ReplaySource(camera.id, value.strip())
    raise SourceError(UNSUPPORTED)


# Snapshots while not monitoring -----------------------------------------------------

def _grab(target, result: list) -> None:
    capture = None
    try:
        capture = cv2.VideoCapture(target)
        if capture.isOpened():
            ok, image = capture.read()
            if ok and image is not None:
                result.append(image)
    except Exception:
        log.debug('Snapshot grab failed', exc_info=True)
    finally:
        if capture is not None:
            capture.release()


def snapshot_image(camera: Camera, timeout: float = SNAPSHOT_TIMEOUT) -> np.ndarray | None:
    """One frame for a camera that is not being monitored, or None.

    Synthetic and replay sources render their first frame; webcam/url/clip sources
    try a one-off OpenCV grab (not the vision pipeline) with a short timeout.
    """
    kind, value = scheme(camera.source)
    try:
        if kind in ('synthetic', 'replay'):
            return build_source(camera).first_frame()
        if kind == 'webcam':
            target = int(value)
        elif kind in ('url', 'clip'):
            target = value
        else:
            return None
    except (SourceError, ValueError, OSError):
        return None
    result: list = []
    thread = threading.Thread(target=_grab, args=(target, result), daemon=True,
                              name=f'snapshot-{camera.id}')
    thread.start()
    thread.join(timeout)
    if not result:
        return None
    image = result[0]
    h, w = image.shape[:2]
    if w > WIDTH:
        image = cv2.resize(image, (WIDTH, int(h * WIDTH / w)), interpolation=cv2.INTER_AREA)
    return image
