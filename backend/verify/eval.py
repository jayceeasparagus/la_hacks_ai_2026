"""python -m verify.eval data/verify

Expects <folder>/<check>/<yes|no>/*.jpg. Prints per check: accuracy, confusion matrix with an
"unclear" column, p50/p95 latency, misclassified files, and a confidence-threshold sweep.
"""

import argparse
import logging
import statistics
import time
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

from policy import llm
from verify.images import check_from_path, label_from_path, list_images, read_image
from verify.verifier import CONFIDENCE_THRESHOLD, VisionAnswer, to_verdict, verify_crop_detailed

THRESHOLDS = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]
MAX_UNCLEAR = 0.20


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the crop verifier on a labeled folder.")
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()

    load_dotenv()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    print(f"model: {'FAKE (offline)' if llm.fake_mode() else llm.verify_model()}")

    samples: dict[str, list[tuple[Path, bool, VisionAnswer | None, float]]] = defaultdict(list)
    for path in list_images(args.folder):
        check, label = check_from_path(path), label_from_path(path)
        image = read_image(path)
        if check is None or label is None or image is None:
            print(f"skipped {path} (needs <check>/<yes|no>/ folders and a readable image)")
            continue
        started = time.monotonic()
        _, raw = verify_crop_detailed(image, check)
        samples[check].append((path, label, raw, (time.monotonic() - started) * 1000))

    if not samples:
        print(f"no labeled images found under {args.folder}")
    for check, rows in sorted(samples.items()):
        _report(check, rows, args.folder)


def _answer(raw: VisionAnswer | None, threshold: float) -> bool | None:
    return None if raw is None else to_verdict(raw, threshold).answer


def _report(check: str, rows, root: Path) -> None:
    n = len(rows)
    answers = [_answer(raw, CONFIDENCE_THRESHOLD) for _, _, raw, _ in rows]
    correct = sum(1 for (_, label, _, _), a in zip(rows, answers) if a == label)
    unclear = answers.count(None)
    print(f"\n== {check}: {n} images, threshold {CONFIDENCE_THRESHOLD:.2f} ==")
    print(f"accuracy {correct}/{n} = {correct / n:.0%}   wrong {n - correct - unclear}   unclear {unclear} ({unclear / n:.0%})")

    print(f"{'':12}{'yes':>6}{'no':>6}{'unclear':>9}")
    for truth in (True, False):
        counts = [sum(1 for (_, label, _, _), a in zip(rows, answers) if label == truth and a == pred)
                  for pred in (True, False, None)]
        print(f"{'truth ' + ('yes' if truth else 'no'):12}{counts[0]:>6}{counts[1]:>6}{counts[2]:>9}")

    latencies = sorted(ms for _, _, _, ms in rows)
    p95 = latencies[min(len(latencies) - 1, round(0.95 * (len(latencies) - 1)))]
    print(f"latency p50 {statistics.median(latencies):.0f} ms   p95 {p95:.0f} ms")

    wrong = [(path, a, raw) for (path, label, raw, _), a in zip(rows, answers) if a != label]
    if wrong:
        print("misclassified:")
        for path, a, raw in wrong:
            said = {True: "yes", False: "no", None: "unclear"}[a]
            detail = f"{raw.answer} {raw.confidence:.2f}: {raw.reason}" if raw else "no model answer"
            print(f"  {path.relative_to(root)} -> {said} ({detail})")

    print("threshold sweep:   thr  wrong  unclear")
    best = None
    for threshold in THRESHOLDS:
        preds = [_answer(raw, threshold) for _, _, raw, _ in rows]
        n_unclear = preds.count(None)
        n_wrong = sum(1 for (_, label, _, _), p in zip(rows, preds) if p is not None and p != label)
        print(f"{'':18}{threshold:.2f}{n_wrong:>7}{n_unclear / n:>9.0%}")
        if n_unclear / n <= MAX_UNCLEAR and (best is None or (n_wrong, n_unclear) < best[1:]):
            best = (threshold, n_wrong, n_unclear)
    if best:
        print(f"best threshold: {best[0]:.2f} ({best[1]} wrong, {best[2] / n:.0%} unclear)")
    else:
        print(f"no threshold keeps unclear under {MAX_UNCLEAR:.0%}")


if __name__ == "__main__":
    main()
