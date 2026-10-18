"""Image-folder helpers shared by verify.cli and verify.eval."""

from pathlib import Path

import cv2
import numpy as np

from verify.prompts import QUESTIONS

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def list_images(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES)


def read_image(path: Path) -> np.ndarray | None:
    """BGR image, or None. np.fromfile handles non-ASCII Windows paths that cv2.imread cannot."""
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None


def check_from_path(path: Path) -> str | None:
    """The check named by a folder in the path, e.g. data/verify/transparent_bag/yes/x.jpg."""
    return next((part for part in path.parts if part in QUESTIONS), None)


def label_from_path(path: Path) -> bool | None:
    """True for a .../yes/... folder, False for .../no/..., else None."""
    for part in reversed(path.parts[:-1]):
        if part in ("yes", "no"):
            return part == "yes"
    return None
