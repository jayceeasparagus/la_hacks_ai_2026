"""Image helpers compatible with Person 1's normalized BGR frame convention."""

from dataclasses import dataclass
from math import ceil, floor

from app.models import Track


def valid_image(image) -> bool:
    if image is None:
        return False
    import numpy as np
    return (isinstance(image, np.ndarray) and image.dtype == np.uint8
            and image.ndim == 3 and image.shape[2] == 3
            and image.shape[0] > 0 and image.shape[1] > 0)


def crop(image, bbox, pad=0.15):
    """Return an owned, padded crop; never hand a mutable capture view to a worker."""
    if not valid_image(image):
        return None
    height, width = image.shape[:2]
    x1, y1, x2, y2 = bbox
    px, py = (x2 - x1) * pad, (y2 - y1) * pad
    left, right = max(0, floor((x1 - px) * width)), min(width, ceil((x2 + px) * width))
    top, bottom = max(0, floor((y1 - py) * height)), min(height, ceil((y2 + py) * height))
    return image[top:bottom, left:right].copy() if right > left and bottom > top else None


@dataclass
class ImageSample:
    image: object
    crop: object
    track: Track
    ts: float
    score: float


def best_sample(previous: ImageSample | None, image, track: Track, ts: float):
    """Prefer large, confident detections; preserve their original frame and bbox."""
    if not valid_image(image):
        return previous
    height, width = image.shape[:2]
    x1, y1, x2, y2 = track.bbox
    score = (x2 - x1) * (y2 - y1) * width * height * track.confidence
    if previous is not None and previous.score >= score:
        return previous
    patch = crop(image, track.bbox)
    if patch is None or patch.size == 0:
        return previous
    return ImageSample(image.copy(), patch, track.model_copy(deep=True), ts, score)
