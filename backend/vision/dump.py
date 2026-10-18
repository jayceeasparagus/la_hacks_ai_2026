"""Dump a clip's tracks so teammates can build the engine without the model.

    python -m vision.dump ../clips/exit_bag.mp4 [--camera-id cam_exit]

writes next to the clip:
    exit_bag.tracks.jsonl    one TrackFrame per line, every frame, deterministic ts
    exit_bag.annotated.mp4   the clip with boxes, classes and track ids drawn

and prints per-class detection counts, unique track ids and likely id switches
(a track that ends and a same-class track that starts within 1 s at almost the
same place).
"""

import argparse
import time
from collections import Counter
from pathlib import Path

import cv2

from vision.annotate import draw_annotations
from vision.detector import CLASSES
from vision.pipeline import VisionPipeline

SWITCH_GAP_SECONDS = 1.0
SWITCH_MIN_IOU = 0.5


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def find_id_switches(tracks: dict[int, dict]) -> list[tuple[int, int, float]]:
    """(old_id, new_id, gap_seconds) for likely switches."""
    switches = []
    for old_id, old in tracks.items():
        for new_id, new in tracks.items():
            if new_id == old_id or new["cls"] != old["cls"]:
                continue
            gap = new["first_ts"] - old["last_ts"]
            if 0 <= gap <= SWITCH_GAP_SECONDS and iou(old["last_bbox"], new["first_bbox"]) >= SWITCH_MIN_IOU:
                switches.append((old_id, new_id, gap))
    return switches


def dump(clip: Path, camera_id: str, imgsz: int) -> None:
    tracks_path = clip.with_suffix(".tracks.jsonl")
    video_path = clip.with_suffix(".annotated.mp4")
    pipe = VisionPipeline(camera_id, f"clip:{clip}", imgsz=imgsz)
    fps = pipe.capture.fps

    counts, frames_with = Counter(), Counter()
    tracks: dict[int, dict] = {}
    writer, frames, start = None, 0, time.monotonic()
    with open(tracks_path, "w", encoding="utf-8") as out:
        for image, tf in pipe.frames():
            out.write(tf.to_json() + "\n")
            annotated = draw_annotations(image, tracks=tf.tracks)
            if writer is None:
                writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), fps,
                                         (tf.width, tf.height))
            writer.write(annotated)

            frames += 1
            counts.update(t.class_name for t in tf.tracks)
            frames_with.update({t.class_name for t in tf.tracks})
            for t in tf.tracks:
                entry = tracks.setdefault(t.track_id, {"cls": t.class_name, "first_ts": tf.ts,
                                                       "first_bbox": t.bbox, "seen": 0})
                entry.update(last_ts=tf.ts, last_bbox=t.bbox, seen=entry["seen"] + 1)
    pipe.stop()
    if writer is not None:
        writer.release()

    elapsed = time.monotonic() - start
    print(f"{clip.name}: {frames} frames in {elapsed:.1f} s ({frames / max(elapsed, 1e-9):.1f} fps)")
    print(f"  wrote {tracks_path.name} and {video_path.name}")
    for cls in CLASSES:
        ids = sorted((i for i, t in tracks.items() if t["cls"] == cls), key=lambda i: -tracks[i]["seen"])
        if not counts[cls]:
            continue
        spans = ", ".join(f"#{i} {tracks[i]['first_ts']:.1f}-{tracks[i]['last_ts']:.1f} s" for i in ids[:4])
        print(f"  {cls:9s} {counts[cls]:6d} detections in {frames_with[cls]:5d} frames, "
              f"{len(ids)} unique ids (longest: {spans})")
    switches = find_id_switches(tracks)
    if switches:
        for old_id, new_id, gap in switches:
            print(f"  likely id switch: {tracks[old_id]['cls']} #{old_id} -> #{new_id} after {gap:.2f} s")
    else:
        print("  no likely id switches")


def main() -> None:
    parser = argparse.ArgumentParser(description="Write <clip>.tracks.jsonl and <clip>.annotated.mp4.")
    parser.add_argument("clips", nargs="+", help="video files (a clip: prefix is optional)")
    parser.add_argument("--camera-id", default=None, help="default: the clip's file name")
    parser.add_argument("--imgsz", type=int, default=640)
    args = parser.parse_args()
    for name in args.clips:
        clip = Path(name.removeprefix("clip:"))
        dump(clip, args.camera_id or clip.stem, args.imgsz)


if __name__ == "__main__":
    main()
