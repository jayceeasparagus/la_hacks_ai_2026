"""Overlay drawing for the live stream and evidence frames.

draw_annotations(frame, zones, tracks, rule_states) returns a new image.
Zone and RuleState are not in the contracts yet, so inputs are read by field
name and may be dataclasses, Pydantic models or dicts:

    zone:       id, name, polygon [[x, y], ...] normalized 0..1
    track:      track_id, class_name (or cls), bbox [x1, y1, x2, y2] normalized
    rule_state: track_id, label ("Exit obstruction"), elapsed (s), duration (s),
                severity ("urgent" | "review"), optional zone_id
"""

import cv2
import numpy as np

FONT = cv2.FONT_HERSHEY_SIMPLEX
# BGR
ZONE_COLOR = (200, 170, 40)
BOX_COLOR = (235, 235, 235)
REVIEW_COLOR = (0, 170, 255)
URGENT_COLOR = (40, 40, 230)
ZONE_ALPHA = 0.22


def _get(obj, *names, default=None):
    for name in names:
        if isinstance(obj, dict):
            if name in obj:
                return obj[name]
        elif hasattr(obj, name):
            return getattr(obj, name)
    return default


def _label(img, text, org, color, scale=0.5, text_color=(255, 255, 255)):
    """Text on a filled background box; org is the box's bottom-left corner."""
    (tw, th), base = cv2.getTextSize(text, FONT, scale, 1)
    x, y = org
    x = max(0, min(x, img.shape[1] - tw - 8))
    y = max(th + base + 4, y)
    cv2.rectangle(img, (x, y - th - base - 4), (x + tw + 8, y), color, -1)
    cv2.putText(img, text, (x + 4, y - base - 2), FONT, scale, text_color, 1, cv2.LINE_AA)
    return tw + 8


def _state_color(state) -> tuple[int, int, int]:
    severity = _get(state, "severity", default="review")
    return URGENT_COLOR if severity == "urgent" else REVIEW_COLOR


def draw_annotations(frame: np.ndarray, zones=(), tracks=(), rule_states=()) -> np.ndarray:
    out = frame.copy()
    h, w = out.shape[:2]

    # Zones: one translucent layer for all fills, crisp outlines on top.
    polygons = []
    for zone in zones:
        points = _get(zone, "polygon", "points", default=[])
        if len(points) >= 3:
            pts = np.array([[int(x * w), int(y * h)] for x, y in points], np.int32)
            polygons.append((zone, pts))
    if polygons:
        layer = out.copy()
        for _, pts in polygons:
            cv2.fillPoly(layer, [pts], ZONE_COLOR)
        cv2.addWeighted(layer, ZONE_ALPHA, out, 1 - ZONE_ALPHA, 0, dst=out)
        for zone, pts in polygons:
            cv2.polylines(out, [pts], True, ZONE_COLOR, 2, cv2.LINE_AA)
            # name at the polygon's top-left, just above its highest edge
            name = str(_get(zone, "name", "id", default="zone"))
            _label(out, name, (int(pts[:, 0].min()), int(pts[:, 1].min()) - 2), ZONE_COLOR, scale=0.5)

    states_by_track: dict[int, list] = {}
    for state in rule_states:
        states_by_track.setdefault(_get(state, "track_id"), []).append(state)

    for track in tracks:
        track_id = _get(track, "track_id")
        x1, y1, x2, y2 = _get(track, "bbox")
        p1, p2 = (int(x1 * w), int(y1 * h)), (int(x2 * w), int(y2 * h))
        states = states_by_track.get(track_id, [])
        color = _state_color(states[0]) if states else BOX_COLOR
        cv2.rectangle(out, p1, p2, color, 2 if states else 1, cv2.LINE_AA)
        cls = _get(track, "class_name", "cls", default="?")
        tag = f"{cls} #{track_id}" if track_id is not None else str(cls)
        _label(out, tag, (p1[0], p1[1]), color if states else (60, 60, 60), scale=0.45)

        # Progress labels inside the box under the tag, e.g. "Exit obstruction 3.2 / 5 s".
        # Inside keeps them on screen for boxes touching the frame edge.
        y = max(p1[1], 0) + 46
        for state in states:
            elapsed = float(_get(state, "elapsed", default=0.0))
            duration = float(_get(state, "duration", default=0.0))
            label = _get(state, "label", "rule_id", default="rule")
            text = f"{label} {elapsed:.1f} / {duration:g} s" if duration else str(label)
            state_color = _state_color(state)
            x = max(p1[0], 0) + 4
            width = _label(out, text, (x, y), state_color, scale=0.45)
            if duration:
                # thin progress bar under the label
                done = max(0.0, min(1.0, elapsed / duration))
                bx = max(0, min(x, w - width))
                cv2.rectangle(out, (bx, y + 1), (bx + width, y + 5), (60, 60, 60), -1)
                cv2.rectangle(out, (bx, y + 1), (bx + int(width * done), y + 5), state_color, -1)
            y += 28
    return out
