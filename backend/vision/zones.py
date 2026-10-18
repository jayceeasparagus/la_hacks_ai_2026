"""Zones: named polygons on a camera image, in normalized 0..1 coordinates.

A track is "in" a zone when its anchor point (bottom-center of the box: where
feet or an object meet the floor) is inside the polygon. No zone drawn means
the whole frame counts, which is fine for a camera aimed tightly at a choke point.

    kind "entrance": people passing through get their carried / worn items checked
    kind "exit":     objects sitting here are timed (blocked-exit rule)

zones.json maps a clip or camera name to its zones:
    {"gate_man_ticket": [{"name": "gate_lane", "kind": "entrance",
                          "polygon": [[0.2, 0.45], [0.8, 0.45], [0.8, 0.95], [0.2, 0.95]]}]}
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

WHOLE_FRAME = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]


@dataclass
class Zone:
    name: str
    kind: str  # "entrance" or "exit"
    polygon: list[list[float]] = field(default_factory=lambda: [p[:] for p in WHOLE_FRAME])
    note: str = ""  # why it was drawn this way (shown in the snapshot viewer)


def anchor(bbox) -> tuple[float, float]:
    """Bottom-center of a normalized [x1, y1, x2, y2] box."""
    return (bbox[0] + bbox[2]) / 2, bbox[3]


def contains(polygon, x: float, y: float) -> bool:
    """Ray-casting point-in-polygon test."""
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def in_zone(zone: Zone, bbox) -> bool:
    return contains(zone.polygon, *anchor(bbox))


def load_zones(path: Path | None, name: str) -> list[Zone]:
    """Zones for one clip/camera. Missing file or entry -> one whole-frame entrance zone."""
    if path and Path(path).exists():
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if name in data:
            return [Zone(**z) for z in data[name]]
    return [Zone("whole_frame", "entrance", note="no zone drawn: whole frame counts")]
