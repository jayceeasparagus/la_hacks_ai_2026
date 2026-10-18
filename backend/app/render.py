"""Drawing for the server: synthetic camera frames and the annotated monitor view.

Synthetic frames are plain gray scenes with each track drawn as a filled box.
Bags are dark unless listed as clear, so Person 2's offline fake verifier
(POLICYLENS_FAKE_LLM=1) judges them 'not clear' and the demo produces a review alert.
"""

import cv2
import numpy as np

from app.models import RuleState, TrackFrame, Zone

WIDTH, HEIGHT = 960, 540
FONT = cv2.FONT_HERSHEY_SIMPLEX
BACKGROUND = 112
# BGR fill colors for synthetic objects
FILL = {
    'person': (150, 140, 130),
    'backpack': (38, 38, 42),
    'handbag': (38, 38, 42),
    'suitcase': (38, 38, 42),
    'chair': (40, 70, 110),
    'camera': (25, 25, 25),
}
CLEAR_FILL = (235, 235, 235)
ZONE_COLOR = (255, 200, 0)
TRACK_COLOR = (90, 220, 90)
PHASE_COLOR = {'timing': (0, 170, 255), 'verifying': (255, 170, 0), 'alerted': (40, 40, 230),
               'compliant': (90, 220, 90), 'cleared': (160, 160, 160)}
JPEG_QUALITY = 80


def _px(image: np.ndarray, x: float, y: float) -> tuple[int, int]:
    h, w = image.shape[:2]
    return int(round(x * w)), int(round(y * h))


def _label(image: np.ndarray, text: str, x: int, y: int, color, scale: float = 0.5) -> None:
    (tw, th), base = cv2.getTextSize(text, FONT, scale, 1)
    x = max(0, min(x, image.shape[1] - tw - 8))
    y = max(th + base + 4, min(y, image.shape[0]))
    cv2.rectangle(image, (x, y - th - base - 4), (x + tw + 8, y), color, -1)
    cv2.putText(image, text, (x + 4, y - base - 2), FONT, scale, (255, 255, 255), 1, cv2.LINE_AA)


def render_scene(tf: TrackFrame, title: str = '', clear_ids: frozenset[int] = frozenset(),
                 size: tuple[int, int] = (WIDTH, HEIGHT)) -> np.ndarray:
    """A synthetic BGR frame for one TrackFrame (no annotations)."""
    width, height = size
    image = np.full((height, width, 3), BACKGROUND, np.uint8)
    cv2.rectangle(image, (0, int(height * 0.62)), (width, height), (95, 95, 95), -1)  # floor
    for track in tf.tracks:
        x1, y1 = _px(image, track.bbox[0], track.bbox[1])
        x2, y2 = _px(image, track.bbox[2], track.bbox[3])
        fill = CLEAR_FILL if track.track_id in clear_ids else FILL[track.object_class]
        cv2.rectangle(image, (x1, y1), (x2, y2), fill, -1)
    if title:
        cv2.putText(image, title, (12, height - 14), FONT, 0.55, (230, 230, 230), 1, cv2.LINE_AA)
    return image


def annotate(image: np.ndarray, zones: list[Zone], tf: TrackFrame | None,
             states: list[RuleState], rule_names: dict[str, str] | None = None) -> np.ndarray:
    """A copy of the frame with zones outlined, boxes labelled and active rule timers."""
    out = np.ascontiguousarray(image, dtype=np.uint8).copy()
    if out.ndim == 2:
        out = cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)
    rule_names = rule_names or {}
    for zone in zones:
        points = np.array([_px(out, x, y) for x, y in zone.polygon], np.int32)
        cv2.polylines(out, [points], True, ZONE_COLOR, 2, cv2.LINE_AA)
        _label(out, zone.name, int(points[:, 0].min()), int(points[:, 1].min()) + 2, (150, 110, 0))
    if tf is None:
        return out
    timers: dict[int, list[RuleState]] = {}
    for state in states:
        if state.phase != 'cleared':
            timers.setdefault(state.track_id, []).append(state)
    for track in tf.tracks:
        p1 = _px(out, track.bbox[0], track.bbox[1])
        p2 = _px(out, track.bbox[2], track.bbox[3])
        active = timers.get(track.track_id, [])
        color = PHASE_COLOR[active[0].phase] if active else TRACK_COLOR
        cv2.rectangle(out, p1, p2, color, 2, cv2.LINE_AA)
        _label(out, f'{track.object_class} #{track.track_id}', p1[0], p1[1], (60, 60, 60))
        for row, state in enumerate(active):
            name = rule_names.get(state.rule_id, state.rule_id)
            text = (f'{name} {state.elapsed_seconds:.1f}/{state.duration_seconds:g}s'
                    f' {state.phase}')
            _label(out, text, p1[0], p2[1] + 20 * (row + 1), PHASE_COLOR[state.phase])
    return out


def encode_jpeg(image: np.ndarray, quality: int = JPEG_QUALITY) -> bytes | None:
    ok, data = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return data.tobytes() if ok else None
