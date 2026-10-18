"""python -m verify.cli <folder> [--check transparent_bag]: a verdict and latency per image."""

import argparse
import logging
import time
from pathlib import Path

from dotenv import load_dotenv

from policy import llm
from verify.images import check_from_path, list_images, read_image
from verify.prompts import QUESTIONS
from verify.verifier import verify_crop


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the crop verifier on a folder of images.")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--check", choices=sorted(QUESTIONS), help="default: taken from the folder name")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    load_dotenv()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    print(f"model: {'FAKE (offline)' if llm.fake_mode() else llm.verify_model()}")

    images = list_images(args.folder)
    if not images:
        print(f"no images found in {args.folder}")
        return
    latencies = []
    for path in images:
        check = args.check or check_from_path(path)
        if check is None:
            print(f"{path}: skipped (pass --check or put it under a transparent_bag/ or professional_camera/ folder)")
            continue
        image = read_image(path)
        if image is None:
            print(f"{path}: could not read image")
            continue
        started = time.monotonic()
        verdict = verify_crop(image, check)
        ms = (time.monotonic() - started) * 1000
        latencies.append(ms)
        answer = {True: "yes", False: "no", None: "unclear"}[verdict.answer]
        print(f"{path.relative_to(args.folder)}  {check}  {answer:<7}  conf {verdict.confidence:.2f}  "
              f"{ms:6.0f} ms  {verdict.reason}")
    if latencies:
        print(f"\n{len(latencies)} images, mean latency {sum(latencies) / len(latencies):.0f} ms")


if __name__ == "__main__":
    main()
