"""python -m verify.crops boxes.csv --out data/verify

Cuts labeled crops out of recorded clips for verify.eval, padded about 15% like the live system.
CSV columns: clip,time_s,x1,y1,x2,y2,check,label
  clip   path to the video (relative to the CSV file)
  x1..y2 box in pixels, or normalized 0-1 if every value is <= 1
  check  transparent_bag | professional_camera
  label  yes | no
"""

import argparse
import csv
from pathlib import Path

import cv2

from verify.prompts import QUESTIONS

PAD = 0.15


def main() -> None:
    parser = argparse.ArgumentParser(description="Cut labeled crops from clips.")
    parser.add_argument("boxes", type=Path)
    parser.add_argument("--out", type=Path, default=Path("data/verify"))
    args = parser.parse_args()

    with args.boxes.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for i, row in enumerate(rows, start=1):
        if row["check"] not in QUESTIONS or row["label"] not in ("yes", "no"):
            print(f"row {i}: bad check or label, skipped")
            continue
        clip = (args.boxes.parent / row["clip"]).resolve()
        frame = _frame_at(clip, float(row["time_s"]))
        if frame is None:
            print(f"row {i}: could not read {clip} at {row['time_s']} s")
            continue
        crop = _padded_crop(frame, [float(row[k]) for k in ("x1", "y1", "x2", "y2")])
        if crop.size == 0:
            print(f"row {i}: empty or inverted box, skipped")
            continue
        folder = args.out / row["check"] / row["label"]
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{clip.stem}_{float(row['time_s']):.1f}s_{i}.jpg"
        cv2.imwrite(str(folder / name), crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
        print(f"row {i}: wrote {folder / name}")


def _frame_at(clip: Path, seconds: float):
    capture = cv2.VideoCapture(str(clip))
    capture.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000)
    ok, frame = capture.read()
    capture.release()
    return frame if ok else None


def _padded_crop(frame, box: list[float]):
    height, width = frame.shape[:2]
    if all(v <= 1 for v in box):
        box = [box[0] * width, box[1] * height, box[2] * width, box[3] * height]
    x1, y1, x2, y2 = box
    pad_x, pad_y = (x2 - x1) * PAD, (y2 - y1) * PAD
    x1, y1 = max(0, int(x1 - pad_x)), max(0, int(y1 - pad_y))
    x2, y2 = min(width, int(x2 + pad_x)), min(height, int(y2 + pad_y))
    return frame[y1:y2, x1:x2]


if __name__ == "__main__":
    main()
