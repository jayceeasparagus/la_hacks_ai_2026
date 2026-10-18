"""python -m verify.ppe_crops <dataset dir> --out <dir> [--per-label 40]

Builds labeled person crops for verify.eval from the Roboflow "Construction Site Safety"
YOLO dataset (CC BY 4.0). For each Person box, the label comes from the gear boxes whose
centre falls inside it:
  hard_hat     yes: a Hardhat box in the top 40% of the person;  no: a NO-Hardhat box there
  safety_vest  yes: a Safety Vest box in the person's torso;       no: a NO-Safety Vest box there
People with conflicting or no gear labels are skipped. Crops are padded 15% like the live
system and written to <out>/<check>/<yes|no>/. Uses the test and valid splits only.
"""

import argparse
import os
import random
from pathlib import Path

import cv2
import numpy as np

CLASSES = ['Hardhat', 'Mask', 'NO-Hardhat', 'NO-Mask', 'NO-Safety Vest', 'Person', 'Safety Cone',
           'Safety Vest', 'machinery', 'vehicle']
# check -> (yes class, no class, vertical band of the person box where the gear sits)
CHECKS = {
    'hard_hat': ('Hardhat', 'NO-Hardhat', (0.0, 0.4)),
    'safety_vest': ('Safety Vest', 'NO-Safety Vest', (0.15, 0.75)),
}
PAD = 0.15
MIN_SIDE_PX = 48


def long_path(path: Path) -> str:
    """Dataset file names are long; on Windows they can exceed MAX_PATH without the long-path prefix."""
    resolved = str(path.resolve())
    prefix = '\\\\?\\'
    return prefix + resolved if os.name == 'nt' and not resolved.startswith('\\\\') else resolved


def read_boxes(label_path: Path) -> list[tuple[str, float, float, float, float]]:
    boxes = []
    with open(long_path(label_path), encoding='utf-8') as stream:
        lines = stream.read().splitlines()
    for line in lines:
        parts = line.split()
        if len(parts) != 5:
            continue  # polygon labels are not used
        cls, cx, cy, w, h = int(parts[0]), *map(float, parts[1:])
        if 0 <= cls < len(CLASSES):
            boxes.append((CLASSES[cls], cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))
    return boxes


def label_person(person, gear, check: str) -> bool | None:
    yes_cls, no_cls, (top, bottom) = CHECKS[check]
    _, x1, y1, x2, y2 = person
    band_top, band_bottom = y1 + top * (y2 - y1), y1 + bottom * (y2 - y1)
    found = set()
    for cls, gx1, gy1, gx2, gy2 in gear:
        cx, cy = (gx1 + gx2) / 2, (gy1 + gy2) / 2
        if cls in (yes_cls, no_cls) and x1 <= cx <= x2 and band_top <= cy <= band_bottom:
            found.add(cls)
    if found == {yes_cls}:
        return True
    if found == {no_cls}:
        return False
    return None


def _overlaps(a, b) -> bool:
    """True if b's box intersects a's padded crop area."""
    _, ax1, ay1, ax2, ay2 = a
    _, bx1, by1, bx2, by2 = b
    px, py = (ax2 - ax1) * PAD, (ay2 - ay1) * PAD
    return bx1 < ax2 + px and bx2 > ax1 - px and by1 < ay2 + py and by2 > ay1 - py


def padded_crop(image, box):
    h, w = image.shape[:2]
    _, x1, y1, x2, y2 = box
    px, py = (x2 - x1) * PAD, (y2 - y1) * PAD
    left, top = max(0, int((x1 - px) * w)), max(0, int((y1 - py) * h))
    right, bottom = min(w, int((x2 + px) * w)), min(h, int((y2 + py) * h))
    return image[top:bottom, left:right]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('dataset', type=Path, help='folder containing test/ and valid/ (e.g. .../css-data)')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--per-label', type=int, default=40, help='crops per check per yes/no label')
    parser.add_argument('--seed', type=int, default=7)
    args = parser.parse_args()

    candidates: dict[tuple[str, bool], list[tuple[Path, tuple]]] = {}
    for split in ('test', 'valid'):
        for label_path in sorted((args.dataset / split / 'labels').glob('*.txt')):
            boxes = read_boxes(label_path)
            people = [b for b in boxes if b[0] == 'Person']
            gear = [b for b in boxes if b[0] != 'Person']
            image_path = args.dataset / split / 'images' / f'{label_path.stem}.jpg'
            for person in people:
                if any(other is not person and _overlaps(person, other) for other in people):
                    continue  # a neighbour's gear in the crop would make the label ambiguous
                for check in CHECKS:
                    label = label_person(person, gear, check)
                    if label is not None:
                        candidates.setdefault((check, label), []).append((image_path, person))

    rng = random.Random(args.seed)
    for (check, label), items in sorted(candidates.items()):
        rng.shuffle(items)
        folder = args.out / check / ('yes' if label else 'no')
        folder.mkdir(parents=True, exist_ok=True)
        written = 0
        for image_path, person in items:
            if written >= args.per_label:
                break
            image = cv2.imdecode(np.fromfile(long_path(image_path), np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                continue
            crop = padded_crop(image, person)
            if min(crop.shape[:2]) < MIN_SIDE_PX:
                continue
            written += 1
            cv2.imwrite(str(folder / f'{image_path.stem[:40]}_{written}.jpg'), crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
        print(f'{check}/{"yes" if label else "no"}: {written} crops (from {len(items)} labeled people)')


if __name__ == '__main__':
    main()
