"""Convert Person 1's draft TrackFrames into the approved contract.

Person 1 emits `class_name`, `conf`, `frame_index`, `width`, `height` and a `ts`
that is unix time for live cameras or clip seconds for clips. The approved
`TrackFrame` needs `object_class`, `confidence`, no extra fields and a `ts` that
strictly increases within one engine session. Bad tracks are dropped, never raised.
"""

from math import isfinite
from operator import index

from pydantic import ValidationError

from app.models import SUPPORTED_OBJECTS, Track, TrackFrame

RESTART_SECONDS = 0.5  # a backwards jump larger than this is a new source session


def _field(obj, *names, default=None):
    for name in names:
        if isinstance(obj, dict):
            if name in obj:
                return obj[name]
        elif hasattr(obj, name):
            return getattr(obj, name)
    return default


def _number(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def convert_track(raw) -> Track | None:
    """One approved Track, or None if the raw track cannot be trusted."""
    try:
        track_id = _field(raw, 'track_id')
        if isinstance(track_id, bool):
            return None
        track_id = index(track_id)
        object_class = _field(raw, 'object_class', 'class_name')
        if object_class not in SUPPORTED_OBJECTS:
            return None
        confidence = _number(_field(raw, 'confidence', 'conf'))
        bbox = list(_field(raw, 'bbox', default=()))
        if confidence is None or len(bbox) != 4:
            return None
        coords = [_number(value) for value in bbox]
        if any(value is None for value in coords):
            return None
        x1, y1, x2, y2 = (min(1.0, max(0.0, value)) for value in coords)
        if x1 >= x2 or y1 >= y2:
            return None
        return Track(track_id=track_id, object_class=object_class, bbox=(x1, y1, x2, y2),
                     confidence=min(1.0, max(0.0, confidence)))
    except (TypeError, ValueError, ValidationError):
        return None


class ContractAdapter:
    """Per-camera converter that also detects source restarts.

    One instance per camera worker. When `convert` reports `restarted`, the caller
    must start a fresh RuleEngine session before passing it the frame.
    """

    def __init__(self, camera_id: str):
        if not camera_id:
            raise ValueError('camera_id is required')
        self.camera_id = camera_id
        self._start: float | None = None
        self._last_source: float | None = None
        self._last_out: float | None = None

    def reset(self) -> None:
        """Forget the session; the next frame starts a new one."""
        self._start = self._last_source = self._last_out = None

    def convert(self, tf) -> tuple[TrackFrame | None, bool]:
        """(frame, restarted). Accepts Person 1's dataclass, a dict with the same fields, or an approved TrackFrame.

        restarted is True on the first frame of a session and whenever source time jumps backwards by more than
        0.5 s (pipeline restart/reconnect): the caller must reset its RuleEngine. Frames whose ts does not strictly
        increase but went back by <= 0.5 s are skipped (None, False). Output ts = source ts - session start ts.
        """
        camera_id = _field(tf, 'camera_id')
        if camera_id != self.camera_id:
            raise ValueError(f'TrackFrame camera_id {camera_id!r} does not match {self.camera_id!r}')
        source_ts = _number(_field(tf, 'ts'))
        if source_ts is None:
            return None, False

        restarted = (self._start is None
                     or source_ts < self._last_source - RESTART_SECONDS)
        if restarted:
            self._start, self._last_out = source_ts, None
        elif source_ts <= self._last_source:
            return None, False
        ts = source_ts - self._start
        if self._last_out is not None and ts <= self._last_out:
            return None, False  # float rounding on large unix timestamps
        self._last_source, self._last_out = source_ts, ts

        best: dict[int, Track] = {}
        try:
            raw_tracks = list(_field(tf, 'tracks', default=None) or [])
        except TypeError:
            raw_tracks = []
        for raw in raw_tracks:
            track = convert_track(raw)
            if track is None:
                continue
            kept = best.get(track.track_id)
            if kept is None or track.confidence > kept.confidence:
                best[track.track_id] = track
        return TrackFrame(camera_id=self.camera_id, ts=ts, tracks=list(best.values())), restarted
