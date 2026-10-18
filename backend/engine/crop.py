"""Padded crops of normalized boxes, same semantics as vision.pipeline.crop.

Kept here so the engine never imports the vision package (and torch).
"""

from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    import numpy as np


def crop(image: 'np.ndarray', bbox: Sequence[float], pad: float = 0.15) -> 'np.ndarray':
    """Crop a normalized [x1, y1, x2, y2] box, padded by pad * box size on each side.

    The padded box is clamped to the image. Returns a copy, so a reused capture
    buffer cannot change a crop that is waiting for verification.
    """
    height, width = image.shape[:2]
    x1, y1, x2, y2 = bbox
    pad_x, pad_y = (x2 - x1) * pad, (y2 - y1) * pad
    left, top = max(0, int((x1 - pad_x) * width)), max(0, int((y1 - pad_y) * height))
    right = min(width, int((x2 + pad_x) * width))
    bottom = min(height, int((y2 + pad_y) * height))
    return image[top:bottom, left:right].copy()
