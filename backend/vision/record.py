"""Record raw test clips from a camera, with a countdown and a live preview.

    python -m vision.record exit_bag                 # webcam:0 -> clips/own/exit_bag.mp4, q to stop
    python -m vision.record exit_bag --seconds 15    # stop automatically after 15 s
    python -m vision.record entrance_phone --source url:http://192.168.1.5:8080/video

The file is written at a constant 30 fps that follows wall-clock time: if the
camera delivers fewer frames, frames are repeated so a bag that sat for 5 s
lasts 5 s in the clip. The preview shows a REC label; the file does not.
Then run:  python -m vision.dump ../clips/own/exit_bag.mp4
"""

import argparse
import time
from pathlib import Path

import cv2

from vision.capture import SINGLE_CAMERA_SIZE, Capture

OUT_DIR = Path(__file__).resolve().parents[2] / "clips" / "own"
FPS = 30


def record(name: str, source: str, seconds: float | None, countdown: int, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.mp4"
    window = f"record {name} (q to stop)"
    with Capture(source, width=SINGLE_CAMERA_SIZE[0]) as cap:
        # Countdown with live preview so you can line up the shot.
        end = time.monotonic() + countdown
        while time.monotonic() < end:
            frame = cap.read()
            if frame is None:
                continue
            view = frame.image.copy()
            left = int(end - time.monotonic()) + 1
            cv2.putText(view, f"starting in {left}", (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 200, 255), 3, cv2.LINE_AA)
            cv2.imshow(window, view)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                cv2.destroyAllWindows()
                raise SystemExit("cancelled")

        writer, written, read, start = None, 0, 0, time.monotonic()
        while True:
            frame = cap.read()
            elapsed = time.monotonic() - start
            if frame is None:
                print(f"[record] waiting for camera ({cap.status})")
                continue
            if writer is None:
                h, w = frame.image.shape[:2]
                writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (w, h))
            read += 1
            # Write this frame as many times as needed to keep the file on wall-clock time.
            target = int(elapsed * FPS) + 1
            while written < target:
                writer.write(frame.image)
                written += 1

            view = frame.image.copy()
            cv2.circle(view, (30, 30), 10, (0, 0, 255), -1)
            cv2.putText(view, f"REC {elapsed:4.1f} s", (50, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2, cv2.LINE_AA)
            cv2.imshow(window, view)
            if cv2.waitKey(1) & 0xFF == ord("q") or (seconds and elapsed >= seconds):
                break
        writer.release()
    cv2.destroyAllWindows()
    print(f"saved {path} ({written / FPS:.1f} s at {FPS} fps; camera delivered {read / max(elapsed, 1e-9):.1f} fps)")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Record a raw test clip with countdown and preview.")
    parser.add_argument("name", help="clip name, e.g. exit_bag (saved as clips/own/<name>.mp4)")
    parser.add_argument("--source", default="webcam:0")
    parser.add_argument("--seconds", type=float, default=None, help="stop automatically (default: press q)")
    parser.add_argument("--countdown", type=int, default=3)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    record(args.name, args.source, args.seconds, args.countdown, args.out)


if __name__ == "__main__":
    main()
