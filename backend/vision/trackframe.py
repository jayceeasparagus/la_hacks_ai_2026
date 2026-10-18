"""DRAFT TrackFrame until Person 4 adds it to backend/app/models.py.

Plain dataclasses with the same field names the Pydantic model should use, so
switching later is an import change. One TrackFrame per processed frame per
camera; dump.py writes them one JSON object per line.

Example JSON:
{"camera_id": "cam_exit", "frame_index": 42, "ts": 1.68, "width": 960, "height": 540,
 "tracks": [{"track_id": 7, "class_name": "backpack", "conf": 0.61,
             "bbox": [0.41, 0.55, 0.52, 0.80]}]}
"""

import json
from dataclasses import asdict, dataclass, field


@dataclass
class Track:
    track_id: int  # ByteTrack id, unique per camera (not across cameras)
    class_name: str  # one of: person, backpack, handbag, suitcase, chair, camera
    conf: float  # detection confidence 0..1 for this frame
    bbox: list[float]  # [x1, y1, x2, y2] normalized 0..1, origin top-left


@dataclass
class TrackFrame:
    camera_id: str  # e.g. "cam_entrance"
    frame_index: int  # frames since this camera's source was opened
    ts: float  # seconds: clip time (index / fps) for clips, unix time for live cameras
    width: int  # pixel size of the frame the bboxes refer to
    height: int
    tracks: list[Track] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @classmethod
    def from_json(cls, line: str) -> "TrackFrame":
        data = json.loads(line)
        data["tracks"] = [Track(**t) for t in data.get("tracks", [])]
        return cls(**data)
