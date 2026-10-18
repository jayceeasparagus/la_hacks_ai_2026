"""Explicit fake/live boundaries; teammate-owned modules are never modified."""

from dataclasses import asdict, is_dataclass
from pathlib import Path
import threading
import time

import cv2

from app.models import TrackFrame
from engine.replay import read_frames


def adapt_track_frame(raw, camera_id, *, origin=0):
    if hasattr(raw, 'model_dump'):
        data = raw.model_dump()
    elif is_dataclass(raw):
        data = asdict(raw)
    else:
        data = raw
    return TrackFrame.model_validate({
        'camera_id': camera_id, 'ts': data['ts'] - origin,
        'tracks': [{
            'track_id': track['track_id'],
            'object_class': track.get('object_class', track.get('class_name')),
            'bbox': track['bbox'],
            'confidence': track.get('confidence', track.get('conf')),
        } for track in data['tracks']],
    })


class FakePipeline:
    """Recorded images plus existing tracks; this does not run object detection."""

    def __init__(self, camera, *, realtime=True):
        if not camera.source.startswith('clip:'):
            raise ValueError('Demo mode requires clip:<video path> plus matching .tracks.jsonl')
        self.camera = camera
        self.path = Path(camera.source[5:])
        self.realtime = realtime
        self.status = 'connecting'
        self._stop = threading.Event()

    def frames(self):
        capture = cv2.VideoCapture(str(self.path))
        try:
            fps = capture.get(cv2.CAP_PROP_FPS)
            if not capture.isOpened() or fps <= 0:
                raise ValueError('Recorded source unavailable')
            started, first_ts, source_camera = time.monotonic(), None, None
            for raw in read_frames(self.path.with_suffix('.tracks.jsonl')):
                if self._stop.is_set():
                    break
                if source_camera is None:
                    source_camera = raw.camera_id
                if source_camera != raw.camera_id:
                    raise ValueError('Track file contains multiple cameras')
                if first_ts is None:
                    first_ts = raw.ts
                if self.realtime and self._stop.wait(max(0, raw.ts - first_ts - (time.monotonic() - started))):
                    break
                index = round(raw.ts * fps)
                if round(capture.get(cv2.CAP_PROP_POS_FRAMES)) != index:
                    capture.set(cv2.CAP_PROP_POS_FRAMES, index)
                ok, image = capture.read()
                if not ok:
                    raise ValueError('Track timestamp exceeds recorded video')
                self.status = 'online'
                yield image, adapt_track_frame(raw, self.camera.id)
            self.status = 'ended'
        finally:
            capture.release()

    def stop(self):
        self._stop.set()


class VisionAdapter:
    """One real pipeline/model per camera; normalizes Person 1's draft objects."""

    def __init__(self, camera, *, multi_camera=False):
        from vision.pipeline import VisionPipeline
        self.camera = camera
        self.pipeline = VisionPipeline(camera.id, camera.source, multi_camera=multi_camera)
        self._origin = None
        self._last_index = None
        self._stop_lock = threading.Lock()
        self._stopped = False

    @property
    def status(self):
        return self.pipeline.status

    def frames(self):
        for image, raw in self.pipeline.frames():
            data = raw.model_dump() if hasattr(raw, 'model_dump') else asdict(raw)
            index = data.get('frame_index')
            if self._origin is None or (index is not None and self._last_index is not None
                                        and index < self._last_index):
                self._origin = data['ts'] if not self.camera.source.startswith('clip:') else 0
            self._last_index = index
            yield image, adapt_track_frame(data, self.camera.id, origin=self._origin)

    def stop(self):
        with self._stop_lock:
            if not self._stopped:
                self._stopped = True
                self.pipeline.stop()
