"""Run up to 3 cameras at once, one thread and one VisionPipeline each.

Each camera owns its own YOLO-World model and ByteTrack state, so track ids
never mix across cameras. A camera that fails to open or drops shows
"offline" and retries every 2 s; nothing it does can stop the others.

    runners = start_cameras({"cam_entrance": "webcam:0", "cam_exit": "url:http://phone:8080/video"})
    image, tf = runners["cam_exit"].latest()        # newest frame + TrackFrame, or None
    runners["cam_exit"].status, runners["cam_exit"].fps

on_frame(camera_id, image, tf) is called from that camera's thread for every
frame; the integration loop (rule engine, stream) can hook in there.

CLI check:  python -m vision.multicam cam_entrance=webcam:0 cam_exit=url:http://192.168.1.5:8080/video
"""

import argparse
import sys
import threading
import time
import traceback
from typing import Callable

import numpy as np

from vision.pipeline import VisionPipeline
from vision.trackframe import TrackFrame

MAX_CAMERAS = 3
RESTART_SECONDS = 2.0

OnFrame = Callable[[str, np.ndarray, TrackFrame], None]


class CameraRunner(threading.Thread):
    def __init__(self, camera_id: str, source: str, multi_camera: bool, imgsz: int = 640,
                 realtime: bool = True, on_frame: OnFrame | None = None):
        super().__init__(name=f"camera-{camera_id}", daemon=True)
        self.camera_id = camera_id
        self.source = source
        self.multi_camera = multi_camera
        self.imgsz = imgsz
        self.realtime = realtime
        self.on_frame = on_frame
        self.pipeline: VisionPipeline | None = None
        self.frames = 0
        self._latest: tuple[np.ndarray, TrackFrame] | None = None
        self._lock = threading.Lock()
        self._stopped = threading.Event()

    @property
    def status(self) -> str:
        """starting, connecting, online, offline, ended, or error (restarting)."""
        if self.pipeline is None:
            return getattr(self, "_status", "starting")
        return self.pipeline.status

    @property
    def fps(self) -> float:
        return self.pipeline.fps if self.pipeline and self.pipeline.status == "online" else 0.0

    def latest(self) -> tuple[np.ndarray, TrackFrame] | None:
        with self._lock:
            return self._latest

    def run(self) -> None:
        while not self._stopped.is_set():
            try:
                self.pipeline = VisionPipeline(self.camera_id, self.source, imgsz=self.imgsz,
                                               realtime=self.realtime, multi_camera=self.multi_camera)
                for image, tf in self.pipeline.frames():
                    if self._stopped.is_set():
                        break
                    with self._lock:
                        self._latest = (image, tf)
                    self.frames += 1
                    if self.on_frame:
                        try:
                            self.on_frame(self.camera_id, image, tf)
                        except Exception:
                            traceback.print_exc()
                if self.pipeline.status == "ended":
                    return  # a clip finished; live sources never end on their own
            except Exception as exc:
                # Never let one camera's failure escape; log it, then rebuild the pipeline.
                print(f"[{self.camera_id}] error: {exc!r}; restarting in {RESTART_SECONDS:.0f} s",
                      file=sys.stderr)
                self._status = "error"
                self.pipeline = None
                self._stopped.wait(RESTART_SECONDS)
            finally:
                if self.pipeline is not None and self._stopped.is_set():
                    self.pipeline.stop()

    def stop(self) -> None:
        self._stopped.set()
        if self.pipeline is not None:
            self.pipeline.stop()


def start_cameras(sources: dict[str, str], imgsz: int = 640, realtime: bool = True,
                  on_frame: OnFrame | None = None) -> dict[str, CameraRunner]:
    if len(sources) > MAX_CAMERAS:
        raise ValueError(f"at most {MAX_CAMERAS} cameras, got {len(sources)}")
    multi = len(sources) > 1
    runners = {cid: CameraRunner(cid, src, multi, imgsz, realtime, on_frame) for cid, src in sources.items()}
    for runner in runners.values():
        runner.start()
    return runners


def stop_cameras(runners: dict[str, CameraRunner]) -> None:
    for runner in runners.values():
        runner.stop()
    for runner in runners.values():
        runner.join(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run several cameras and report per-camera FPS.")
    parser.add_argument("cameras", nargs="+", help="camera_id=source, e.g. cam_exit=webcam:1")
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--imgsz", type=int, default=640)
    args = parser.parse_args()

    sources = dict(c.split("=", 1) for c in args.cameras)
    runners = start_cameras(sources, imgsz=args.imgsz)
    start = time.monotonic()
    first_frame: dict[str, float] = {}
    try:
        while time.monotonic() - start < args.seconds:
            time.sleep(2)
            parts = []
            for cid, r in runners.items():
                if r.frames and cid not in first_frame:
                    first_frame[cid] = time.monotonic()
                latest = r.latest()
                n = len(latest[1].tracks) if latest else 0
                parts.append(f"{cid}: {r.status:10s} {r.fps:4.1f} fps {n} tracks")
            print(f"t={time.monotonic() - start:5.1f}s  " + " | ".join(parts), flush=True)
    finally:
        stop_cameras(runners)

    end = time.monotonic()
    for cid, r in runners.items():
        if cid in first_frame:
            print(f"{cid}: {r.frames} frames, {r.frames / (end - first_frame[cid]):.1f} fps average")
        else:
            print(f"{cid}: no frames ({r.status})")


if __name__ == "__main__":
    main()
