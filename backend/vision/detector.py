"""YOLO-World open-vocabulary detector for the classes our rules use.

Each prompt the model sees maps to one contract class name, so we can try
wording like "DSLR camera" while the rest of the system still sees "camera".
Per-class confidence thresholds live in CONFIDENCE; the model runs at the
lowest of them and we filter per class afterwards.

CLI check:  python -m vision.detector webcam:0 --seconds 15 --show
            python -m vision.detector clip:../clips/exit_bag.mp4
"""

import argparse
import os
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import torch

# Fail loudly instead of letting ultralytics pip-install packages at runtime.
# Needs: ultralytics, opencv-python, and git+https://github.com/ultralytics/CLIP.git
os.environ.setdefault("YOLO_AUTOINSTALL", "false")
from ultralytics import YOLO  # noqa: E402

from vision.capture import SINGLE_CAMERA_SIZE, Capture

WEIGHTS = Path(__file__).parent / "weights" / "yolov8s-worldv2.pt"
TRACKER_CFG = Path(__file__).parent / "bytetrack.yaml"

# prompt given to YOLO-World -> class name used by the rest of the system
PROMPTS = {
    "person": "person",
    "backpack": "backpack",
    "handbag": "handbag",
    "suitcase": "suitcase",
    "chair": "chair",
    "camera": "camera",
}

# minimum confidence per contract class
CONFIDENCE = {
    "person": 0.35,
    "backpack": 0.25,
    "handbag": 0.25,
    "suitcase": 0.25,
    "chair": 0.30,
    "camera": 0.20,
}


@dataclass
class Detection:
    cls: str  # contract class name
    conf: float
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 normalized to 0..1
    track_id: int | None = None  # filled in by tracking


def pick_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def load_model(prompts: dict[str, str] = PROMPTS) -> YOLO:
    """One model per camera: ultralytics keeps tracker state on the model."""
    model = YOLO(str(WEIGHTS))
    model.set_classes(list(prompts))
    return model


class Detector:
    def __init__(self, prompts: dict[str, str] = PROMPTS, confidence: dict[str, float] = CONFIDENCE,
                 device: str | None = None, imgsz: int = 640):
        self.prompts = prompts
        self.confidence = confidence
        self.device = device or pick_device()
        self.imgsz = imgsz
        self.model = load_model(prompts)
        # model output index -> contract class name
        self.class_names = [prompts[p] for p in prompts]
        self.min_conf = min(confidence[c] for c in self.class_names)

    def detect(self, image: np.ndarray) -> list[Detection]:
        result = self.model.predict(image, conf=self.min_conf, imgsz=self.imgsz, agnostic_nms=True,
                                    device=self.device, verbose=False)[0]
        return self.to_detections(result)

    def track(self, image: np.ndarray) -> list[Detection]:
        """Detect and track with ByteTrack. Ids persist across calls on this Detector.

        The tracker sees boxes down to its low threshold (0.1) so it can keep
        tracks alive through weak frames; per-class thresholds apply afterwards.
        NMS is class-agnostic: YOLO-World often labels one bag as both "backpack"
        and "handbag", which would otherwise become two tracks and two alerts.
        """
        result = self.model.track(image, persist=True, tracker=str(TRACKER_CFG), conf=0.1, agnostic_nms=True,
                                  imgsz=self.imgsz, device=self.device, verbose=False)[0]
        return [d for d in self.to_detections(result) if d.track_id is not None]

    def reset_tracker(self) -> None:
        """Forget all tracks, e.g. before replaying a clip from the start."""
        predictor = self.model.predictor
        for tracker in getattr(predictor, "trackers", None) or []:
            tracker.reset()

    def to_detections(self, result) -> list[Detection]:
        """Convert one ultralytics result (predict or track) to filtered Detections."""
        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            return []
        xyxyn = boxes.xyxyn.cpu().numpy()
        confs = boxes.conf.cpu().numpy()
        classes = boxes.cls.cpu().numpy().astype(int)
        ids = boxes.id.cpu().numpy().astype(int) if boxes.id is not None else [None] * len(boxes)

        detections = []
        for box, conf, cls_index, track_id in zip(xyxyn, confs, classes, ids):
            cls = self.class_names[cls_index]
            if conf < self.confidence[cls]:
                continue
            bbox = tuple(round(float(v), 4) for v in box)
            detections.append(Detection(cls, round(float(conf), 3), bbox,
                                        None if track_id is None else int(track_id)))
        return detections


def draw_detections(image: np.ndarray, detections: list[Detection]) -> np.ndarray:
    """Plain debug boxes; the real overlay lives in annotate.py."""
    out = image.copy()
    h, w = out.shape[:2]
    for d in detections:
        x1, y1, x2, y2 = (int(d.bbox[0] * w), int(d.bbox[1] * h), int(d.bbox[2] * w), int(d.bbox[3] * h))
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 200, 255), 2)
        label = f"{d.cls} {d.conf:.2f}" + (f" #{d.track_id}" if d.track_id is not None else "")
        cv2.putText(out, label, (x1, max(y1 - 6, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1, cv2.LINE_AA)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Run YOLO-World on a source and report FPS and class counts.")
    parser.add_argument("source", help='"webcam:0", "url:<stream>" or "clip:<path>"')
    parser.add_argument("--seconds", type=float, default=15, help="how long to run (live sources)")
    parser.add_argument("--width", type=int, default=SINGLE_CAMERA_SIZE[0])
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", default=None, help="cuda, mps or cpu (default: auto)")
    parser.add_argument("--camera-prompt", default=None,
                        help='replace the "camera" prompt, e.g. "DSLR camera" or "video camera"')
    parser.add_argument("--track", action="store_true", help="track with ByteTrack and report track ids")
    parser.add_argument("--show", action="store_true", help="show boxes in a window (q to quit)")
    args = parser.parse_args()

    prompts = dict(PROMPTS)
    if args.camera_prompt:
        del prompts["camera"]
        prompts[args.camera_prompt] = "camera"

    detector = Detector(prompts=prompts, device=args.device, imgsz=args.imgsz)
    print(f"device={detector.device} imgsz={args.imgsz} prompts={list(prompts)}")

    counts, frames_with = Counter(), Counter()
    tracks: dict[int, dict] = {}  # track_id -> cls, first, last, seen
    frames, infer_total, start = 0, 0.0, None
    with Capture(args.source, width=args.width) as cap:
        while True:
            frame = cap.read()
            if frame is None:
                if cap.ended:
                    break
                continue
            start = start or time.monotonic()
            if cap.kind != "clip" and time.monotonic() - start > args.seconds:
                break
            t0 = time.perf_counter()
            detections = detector.track(frame.image) if args.track else detector.detect(frame.image)
            infer_total += time.perf_counter() - t0
            frames += 1
            counts.update(d.cls for d in detections)
            frames_with.update({d.cls for d in detections})
            for d in detections:
                if d.track_id is not None:
                    t = tracks.setdefault(d.track_id, {"cls": d.cls, "first": frames, "last": frames, "seen": 0})
                    t["last"], t["seen"] = frames, t["seen"] + 1
            if args.show:
                cv2.imshow("detector", draw_detections(frame.image, detections))
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    if args.show:
        cv2.destroyAllWindows()

    if not frames:
        print("no frames read")
        return
    elapsed = time.monotonic() - start
    print(f"{frames} frames, {frames / elapsed:.1f} fps end to end, {1000 * infer_total / frames:.0f} ms per inference")
    for cls in PROMPTS:
        print(f"  {cls:9s} {counts[cls]:6d} detections in {frames_with[cls]:5d} frames")
    if args.track:
        print("tracks (frames are 1-based; seen = frames the id was reported):")
        for cls in PROMPTS:
            ids = sorted((t for t in tracks.items() if t[1]["cls"] == cls), key=lambda t: -t[1]["seen"])
            if not ids:
                continue
            longest = ", ".join(f"#{i} {t['first']}-{t['last']} seen {t['seen']}" for i, t in ids[:4])
            print(f"  {cls:9s} {len(ids):3d} unique ids; longest: {longest}")


if __name__ == "__main__":
    main()
