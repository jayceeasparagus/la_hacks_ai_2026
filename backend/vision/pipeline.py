"""VisionPipeline: one camera -> (frame, TrackFrame) pairs.

Each pipeline owns its own Capture and Detector (and so its own YOLO model and
ByteTrack state), so run one per camera, each in its own thread.

    pipe = VisionPipeline("cam_exit", "webcam:0")
    for image, tf in pipe.frames():
        ...                                   # rule engine goes here
    clip = pipe.recent_frames(4)              # [(ts, image), ...] for evidence
    patch = crop(image, tf.tracks[0].bbox)    # padded crop for Gemini

CLI check:  python -m vision.pipeline webcam:0 --camera-id cam_entrance --seconds 10
"""

import argparse
import threading
import time
from collections import deque
from typing import Iterator

import cv2
import numpy as np

from vision.capture import MULTI_CAMERA_WIDTH, SINGLE_CAMERA_SIZE, Capture
from vision.detector import Detector
from vision.trackframe import Track, TrackFrame

BUFFER_SECONDS = 10.0
BUFFER_JPEG_QUALITY = 85  # raw 720p frames would be ~350 MB per camera for 10 s


def crop(image: np.ndarray, bbox, pad: float = 0.15) -> np.ndarray:
    """Crop a normalized [x1, y1, x2, y2] box, padded by pad * box size on each side."""
    h, w = image.shape[:2]
    x1, y1, x2, y2 = bbox
    pad_x, pad_y = (x2 - x1) * pad, (y2 - y1) * pad
    left, top = max(0, int((x1 - pad_x) * w)), max(0, int((y1 - pad_y) * h))
    right, bottom = min(w, int((x2 + pad_x) * w)), min(h, int((y2 + pad_y) * h))
    return image[top:bottom, left:right].copy()


class VisionPipeline:
    def __init__(self, camera_id: str, source: str, width: int | None = None, imgsz: int = 640,
                 realtime: bool = False, multi_camera: bool = False):
        """width defaults to 1280, or 960 when multi_camera is True."""
        self.camera_id = camera_id
        self.source = source
        width = width or (MULTI_CAMERA_WIDTH if multi_camera else SINGLE_CAMERA_SIZE[0])
        self.detector = Detector(imgsz=imgsz)
        self.capture = Capture(source, width=width, realtime=realtime)
        self.fps = 0.0  # processed frames per second, measured over ~1 s windows
        self._buffer: deque[tuple[float, bytes]] = deque()
        self._buffer_lock = threading.Lock()
        self._stopped = False

    @property
    def status(self) -> str:
        """connecting, online, offline, or ended (clips)."""
        return self.capture.status

    def frames(self) -> Iterator[tuple[np.ndarray, TrackFrame]]:
        """Yield (image, TrackFrame) until stop() or the clip ends.

        Live sources that drop are retried by Capture; this keeps waiting meanwhile.
        """
        window_start, window_frames = time.monotonic(), 0
        while not self._stopped:
            frame = self.capture.read()
            if frame is None:
                if self.capture.ended:
                    return
                self.fps = 0.0
                continue

            detections = self.detector.track(frame.image)
            h, w = frame.image.shape[:2]
            tf = TrackFrame(
                camera_id=self.camera_id,
                frame_index=frame.index,
                ts=round(frame.ts, 3),
                width=w,
                height=h,
                tracks=[Track(d.track_id, d.cls, d.conf, list(d.bbox)) for d in detections],
            )
            self._remember(frame.ts, frame.image)

            window_frames += 1
            elapsed = time.monotonic() - window_start
            if elapsed >= 1.0:
                self.fps = window_frames / elapsed
                window_start, window_frames = time.monotonic(), 0

            yield frame.image, tf

    def _remember(self, ts: float, image: np.ndarray) -> None:
        ok, jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, BUFFER_JPEG_QUALITY])
        if not ok:
            return
        with self._buffer_lock:
            self._buffer.append((ts, jpeg.tobytes()))
            while self._buffer and ts - self._buffer[0][0] > BUFFER_SECONDS:
                self._buffer.popleft()

    def recent_frames(self, seconds: float) -> list[tuple[float, np.ndarray]]:
        """The last `seconds` of frames (at most 10 s) as (ts, image), oldest first. Thread safe."""
        with self._buffer_lock:
            if not self._buffer:
                return []
            newest = self._buffer[-1][0]
            chosen = [(ts, data) for ts, data in self._buffer if newest - ts <= seconds]
        return [(ts, cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)) for ts, data in chosen]

    def stop(self) -> None:
        self._stopped = True
        self.capture.release()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the vision pipeline and print TrackFrames.")
    parser.add_argument("source", help='"webcam:0", "url:<stream>" or "clip:<path>"')
    parser.add_argument("--camera-id", default="cam_test")
    parser.add_argument("--seconds", type=float, default=10, help="how long to run (live sources)")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--multi", action="store_true", help="use the 960 px multi-camera width")
    parser.add_argument("--realtime", action="store_true", help="play clips at true speed")
    parser.add_argument("--show", action="store_true", help="show the annotated feed (q to quit)")
    parser.add_argument("--demo-zone", action="store_true",
                        help="with --show: time non-person objects in a test zone on the right half")
    args = parser.parse_args()
    if args.show:
        args.seconds = float("inf")  # run until q

    pipe = VisionPipeline(args.camera_id, args.source, imgsz=args.imgsz,
                          realtime=args.realtime, multi_camera=args.multi)
    start, last_print, frames, last = None, 0.0, 0, None
    zone = {"name": "test_zone", "polygon": [[0.55, 0.35], [0.97, 0.35], [0.97, 0.97], [0.55, 0.97]]}
    entered: dict[int, float] = {}  # track_id -> ts it entered the test zone
    try:
        for image, tf in pipe.frames():
            start = start or time.monotonic()
            frames += 1
            last = (image, tf)
            if args.show:
                from vision.annotate import draw_annotations
                zones, states = [], []
                if args.demo_zone:
                    zones = [zone]
                    (zx1, zy1), (zx2, zy2) = zone["polygon"][0], zone["polygon"][2]
                    inside = set()
                    for t in tf.tracks:
                        cx, cy = (t.bbox[0] + t.bbox[2]) / 2, t.bbox[3]  # bottom-center
                        if t.class_name != "person" and zx1 <= cx <= zx2 and zy1 <= cy <= zy2:
                            inside.add(t.track_id)
                            entered.setdefault(t.track_id, tf.ts)
                            elapsed = tf.ts - entered[t.track_id]
                            states.append({"track_id": t.track_id, "label": "In zone", "elapsed": elapsed,
                                           "duration": 5, "severity": "urgent" if elapsed >= 5 else "review"})
                    for track_id in list(entered):
                        if track_id not in inside:
                            del entered[track_id]
                view = draw_annotations(image, zones, tf.tracks, states)
                cv2.putText(view, f"{pipe.camera_id}  {pipe.fps:.1f} fps", (10, view.shape[0] - 12),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
                cv2.imshow(f"PolicyLens vision - {pipe.camera_id}", view)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
            now = time.monotonic()
            if now - last_print >= 2.0:
                print(f"[{pipe.camera_id}] fps={pipe.fps:.1f} {tf.to_json()[:300]}")
                last_print = now
            if pipe.capture.kind != "clip" and now - start > args.seconds:
                break
    finally:
        pipe.stop()
        if args.show:
            cv2.destroyAllWindows()

    if not last:
        print(f"no frames (status={pipe.status})")
        return
    image, tf = last
    elapsed = time.monotonic() - start
    print(f"{frames} TrackFrames in {elapsed:.1f} s = {frames / elapsed:.1f} fps")
    for seconds in (4, 10, 30):
        buffered = pipe.recent_frames(seconds)
        span = buffered[-1][0] - buffered[0][0] if buffered else 0
        print(f"recent_frames({seconds}): {len(buffered)} frames spanning {span:.1f} s")
    assert TrackFrame.from_json(tf.to_json()) == tf, "TrackFrame JSON round trip failed"
    print("TrackFrame JSON round trip ok")
    for t in tf.tracks[:3]:
        patch = crop(image, t.bbox)
        print(f"crop #{t.track_id} {t.class_name}: {patch.shape[1]}x{patch.shape[0]} px")


if __name__ == "__main__":
    main()
