"""Frame capture for webcams, phone/IP streams and recorded clips.

Sources are strings:
    webcam:0                      local webcam by index
    url:http://192.168.1.5:8080   phone app stream (http MJPEG or rtsp://...)
    clip:../clips/exit_bag.mp4    recorded file

Clips are deterministic: ts = frame_index / file_fps, frames are never dropped,
and playback runs as fast as possible unless realtime=True.
Live sources read in their own thread and always serve the newest frame. If a
live source fails to open or drops, status becomes "offline" and it retries
every 2 s without raising.

CLI check:  python -m vision.capture webcam:0 --seconds 10 --show
"""

import argparse
import sys
import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np

SINGLE_CAMERA_SIZE = (1280, 720)
MULTI_CAMERA_WIDTH = 960
RETRY_SECONDS = 2.0

# Hide OpenCV's per-attempt warnings; we report offline cameras ourselves.
cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)


@dataclass
class Frame:
    image: np.ndarray  # BGR, already resized
    ts: float  # seconds: clip time for clips, wall clock (time.time()) for live
    index: int  # frame number since the source was opened
    full: np.ndarray | None = None  # original resolution, for high-detail crops


def parse_source(source: str) -> tuple[str, str]:
    kind, sep, value = source.partition(":")
    if not sep or kind not in ("webcam", "url", "clip") or not value:
        raise ValueError(f'bad source {source!r}: use "webcam:N", "url:<stream>" or "clip:<path>"')
    if kind == "webcam" and not value.isdigit():
        raise ValueError(f"webcam index must be a number, got {value!r}")
    return kind, value


def resize_to_width(image: np.ndarray, width: int) -> np.ndarray:
    h, w = image.shape[:2]
    if w <= width:
        return image
    return cv2.resize(image, (width, round(h * width / w)), interpolation=cv2.INTER_AREA)


def _open(kind: str, value: str) -> cv2.VideoCapture:
    if kind == "webcam":
        # DirectShow opens much faster than the default MSMF backend on Windows.
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        cap = cv2.VideoCapture(int(value), backend)
        # Always ask for 720p MJPG (webcams reject odd sizes like 960x540 and
        # raw 720p is often capped near 15-20 fps); resize_to_width shrinks it after.
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, SINGLE_CAMERA_SIZE[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, SINGLE_CAMERA_SIZE[1])
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    else:
        cap = cv2.VideoCapture(value)
    return cap


class Capture:
    """One camera or clip. Call read() in a loop; it returns None when a clip ends.

    width: 1280 when one camera runs, MULTI_CAMERA_WIDTH when two or more run.
    """

    def __init__(self, source: str, width: int = SINGLE_CAMERA_SIZE[0], realtime: bool = False):
        self.source = source
        self.kind, self.value = parse_source(source)
        self.width = width
        self.realtime = realtime
        self.status = "connecting"  # then "online", "offline", or "ended" for clips
        self.fps = 0.0  # file fps for clips, measured fps for live sources
        self._index = 0
        self._stopped = False

        if self.kind == "clip":
            self._cap = _open(self.kind, self.value)
            if not self._cap.isOpened():
                raise FileNotFoundError(f"cannot open clip {self.value!r}")
            self.fps = self._cap.get(cv2.CAP_PROP_FPS) or 30.0
            self.status = "online"
            self._start_wall = None
        else:
            self._latest: Frame | None = None
            self._new_frame = threading.Condition()
            self._thread = threading.Thread(target=self._read_live, name=f"capture-{source}", daemon=True)
            self._thread.start()

    # ---- clips -------------------------------------------------------------

    def _read_clip(self) -> Frame | None:
        ok, image = self._cap.read()
        if not ok:
            self.status = "ended"
            return None
        ts = self._index / self.fps
        if self.realtime:
            if self._start_wall is None:
                self._start_wall = time.monotonic()
            delay = self._start_wall + ts - time.monotonic()
            if delay > 0:
                time.sleep(delay)
        frame = Frame(resize_to_width(image, self.width), ts, self._index, full=image)
        self._index += 1
        return frame

    # ---- live sources --------------------------------------------------------

    def _read_live(self) -> None:
        while not self._stopped:
            cap = _open(self.kind, self.value)
            if not cap.isOpened():
                cap.release()
                self._set_offline(f"cannot open {self.source}")
                time.sleep(RETRY_SECONDS)
                continue

            window_start, window_frames = time.monotonic(), 0
            while not self._stopped:
                ok, image = cap.read()
                if not ok:
                    break
                self.status = "online"
                frame = Frame(resize_to_width(image, self.width), time.time(), self._index, full=image)
                self._index += 1
                with self._new_frame:
                    self._latest = frame
                    self._new_frame.notify_all()

                window_frames += 1
                elapsed = time.monotonic() - window_start
                if elapsed >= 1.0:
                    self.fps = window_frames / elapsed
                    window_start, window_frames = time.monotonic(), 0

            cap.release()
            if not self._stopped:
                self._set_offline(f"lost {self.source}")
                time.sleep(RETRY_SECONDS)

    def _set_offline(self, reason: str) -> None:
        if self.status != "offline":
            print(f"[capture] {reason}; retrying every {RETRY_SECONDS:.0f} s", file=sys.stderr)
        self.status = "offline"
        self.fps = 0.0

    def _wait_live(self, timeout: float) -> Frame | None:
        """Newest frame not yet returned, or None if none arrives within timeout."""
        with self._new_frame:
            last = getattr(self, "_last_returned", -1)
            self._new_frame.wait_for(lambda: self._latest is not None and self._latest.index != last or self._stopped, timeout)
            frame = self._latest
            if frame is None or frame.index == last:
                return None
            self._last_returned = frame.index
            return frame

    # ---- public ----------------------------------------------------------------

    def read(self, timeout: float = 1.0) -> Frame | None:
        """Clips: the next frame, or None at end of file.
        Live: the newest frame, or None if the source is offline (call again to keep waiting)."""
        if self.kind == "clip":
            return self._read_clip()
        return self._wait_live(timeout)

    @property
    def ended(self) -> bool:
        return self.kind == "clip" and self.status == "ended"

    def release(self) -> None:
        self._stopped = True
        if self.kind == "clip":
            self._cap.release()
        else:
            with self._new_frame:
                self._new_frame.notify_all()
            self._thread.join(timeout=3)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()


def main() -> None:
    parser = argparse.ArgumentParser(description="Open a source and report FPS and frame size.")
    parser.add_argument("source", help='"webcam:0", "url:<stream>" or "clip:<path>"')
    parser.add_argument("--seconds", type=float, default=10, help="how long to read (live sources)")
    parser.add_argument("--width", type=int, default=SINGLE_CAMERA_SIZE[0])
    parser.add_argument("--realtime", action="store_true", help="play clips at true speed")
    parser.add_argument("--show", action="store_true", help="show frames in a window (q to quit)")
    args = parser.parse_args()

    with Capture(args.source, width=args.width, realtime=args.realtime) as cap:
        start = time.monotonic()
        frames, first_ts, last, size, first_wall = 0, None, None, None, None
        while time.monotonic() - start < args.seconds or cap.kind == "clip":
            frame = cap.read()
            if frame is None:
                if cap.ended:
                    break
                print(f"[capture] waiting, status={cap.status}")
                continue
            frames += 1
            first_wall = time.monotonic() if first_wall is None else first_wall
            first_ts = frame.ts if first_ts is None else first_ts
            last, size = frame, frame.image.shape[1::-1]
            if args.show:
                cv2.imshow(args.source, frame.image)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
        # Measure from the first frame so camera open time (~2 s) is not counted.
        elapsed = time.monotonic() - (first_wall or start)
        if args.show:
            cv2.destroyAllWindows()

    if not frames:
        print(f"{args.source}: no frames read (status={cap.status})")
        return
    print(f"{args.source}: {frames} frames in {elapsed:.1f} s = {frames / elapsed:.1f} fps read, size {size[0]}x{size[1]}")
    print(f"  ts first={first_ts:.3f} last={last.ts:.3f}, last index={last.index}, source fps={cap.fps:.1f}")


if __name__ == "__main__":
    main()
