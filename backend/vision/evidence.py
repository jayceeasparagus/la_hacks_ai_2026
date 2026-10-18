"""Evidence collection: turn tracks + zones into "ask Gemini about this" events.

Two paths, per the hybrid design:

  Person path (entrance zones): every person whose anchor is in an entrance zone
  starts a *visit*. During the visit we keep the 2 best crops of that person
  (cut from the full-resolution frame) plus close-ups of bags/cameras attached
  to them. When the visit ends (gone > 1 s) or has lasted MAX_WAIT seconds, one
  PersonEvent is emitted -> one batched Gemini request per person per visit.

  Object path (exit zones): bags/chairs whose anchor sits in an exit zone, and
  that nobody is holding, are timed locally. At EXIT_SECONDS one ExitEvent is
  emitted -> one Gemini confirmation before the urgent alert. One per object visit.

No Gemini calls happen here; vision.gemini_request turns events into requests.
"""

from dataclasses import dataclass, field

import cv2
import numpy as np

from vision.trackframe import Track, TrackFrame
from vision.zones import Zone, in_zone

GRACE_SECONDS = 1.0  # missed frames shorter than this do not end a visit
MAX_WAIT = 4.0  # send a person request after this long in the zone even if they are still there
MIN_VISIT_SECONDS = 0.3
MIN_VISIT_FRAMES = 3
MIN_PERSON_HEIGHT_PX = 60  # in the full-resolution frame; smaller crops are useless to Gemini
EXIT_SECONDS = 5.0
CROPS_PER_VISIT = 2
MIN_CROP_GAP = 0.5  # seconds between the 2 kept crops, so they show different moments
CARRIED_CLASSES = {"backpack", "handbag", "suitcase", "camera", "chair"}  # chair: YOLO sometimes calls a held suitcase a chair
OBJECT_CLASSES = {"backpack", "handbag", "suitcase", "chair"}  # timed in exit zones
ATTACH_OVERLAP = 0.5  # share of an object's box inside a person's box to count as carried
MIN_ATTACHED_FRAMES = 3  # a carried-object close-up needs this many sightings (drops 1-frame flickers)
SECOND_CROP_MIN = 0.6  # keep crop 2 only if its score and size are >= 60% of crop 1's
CONTEXT_WIDTH = 960


def box_area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def intersection(a, b) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def iou(a, b) -> float:
    inter = intersection(a, b)
    union = box_area(a) + box_area(b) - inter
    return inter / union if union > 0 else 0.0


def crop_full(full: np.ndarray, bbox, pad: float = 0.15, max_side: int = 768, outline: bool = False) -> np.ndarray:
    """Padded crop from the full-resolution frame, downscaled so the long side <= max_side.
    outline=True draws a thin green box around bbox so Gemini knows who the subject is in a crowd."""
    h, w = full.shape[:2]
    x1, y1, x2, y2 = bbox
    px, py = (x2 - x1) * pad, (y2 - y1) * pad
    left, top = max(0, int((x1 - px) * w)), max(0, int((y1 - py) * h))
    right, bottom = min(w, int((x2 + px) * w)), min(h, int((y2 + py) * h))
    out = full[top:bottom, left:right]
    if outline and out.size:
        out = out.copy()
        t = max(2, (bottom - top) // 200)
        cv2.rectangle(out, (int(x1 * w) - left, int(y1 * h) - top), (int(x2 * w) - left, int(y2 * h) - top), (0, 255, 0), t)
    scale = max_side / max(out.shape[:2]) if out.size else 1.0
    if scale < 1.0:
        out = cv2.resize(out, (int(out.shape[1] * scale), int(out.shape[0] * scale)), interpolation=cv2.INTER_AREA)
    return out.copy()


def sharpness(img: np.ndarray) -> float:
    """Variance of the Laplacian on a fixed-height grayscale copy (higher = sharper)."""
    if img.size == 0:
        return 0.0
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (max(1, int(gray.shape[1] * 256 / gray.shape[0])), 256))
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


@dataclass
class Candidate:
    ts: float
    frame_index: int
    bbox: list[float]
    crop: np.ndarray
    score: float
    metrics: dict
    context: np.ndarray | None = None  # downscaled full frame at this moment, for the viewer


@dataclass
class Visit:
    track_id: int
    cls: str
    zone: Zone
    first_ts: float
    last_ts: float
    frames: int = 0
    candidates: list[Candidate] = field(default_factory=list)  # best first, at most CROPS_PER_VISIT
    attached: dict[int, Candidate] = field(default_factory=dict)  # object track id -> best close-up
    attached_cls: dict[int, str] = field(default_factory=dict)
    attached_frames: dict[int, int] = field(default_factory=dict)
    sent: bool = False
    # object path
    unattended_seconds: float = 0.0
    last_unattended_ts: float | None = None


@dataclass
class PersonEvent:
    visit: Visit
    trigger: str  # "left_zone", "max_wait", "clip_end"


@dataclass
class ExitEvent:
    visit: Visit
    zone_crop: np.ndarray
    object_crop: np.ndarray
    context: np.ndarray


@dataclass
class Skipped:
    track_id: int
    zone: str
    reason: str
    seconds: float


class EvidenceCollector:
    def __init__(self, zones: list[Zone], draw_context=None):
        self.zones = zones
        self.entrances = [z for z in zones if z.kind == "entrance"]
        self.exits = [z for z in zones if z.kind == "exit"]
        self.person_visits: dict[tuple[str, int], Visit] = {}
        self.object_visits: dict[tuple[str, int], Visit] = {}
        self.skipped: list[Skipped] = []
        # callable(image, tf, highlight_bbox) -> annotated image; injected so this module stays drawing-free
        self.draw_context = draw_context

    # ---- per frame -------------------------------------------------------------

    def update(self, tf: TrackFrame, image: np.ndarray, full: np.ndarray) -> list:
        events: list = []
        people = [t for t in tf.tracks if t.class_name == "person"]
        objects = [t for t in tf.tracks if t.class_name != "person"]
        carrier = self._carriers(people, objects)  # object track id -> person track id

        for zone in self.entrances:
            for p in people:
                if in_zone(zone, p.bbox):
                    self._update_person(zone, p, people, objects, carrier, tf, image, full)
        for zone in self.exits:
            for o in objects:
                if o.class_name in OBJECT_CLASSES and in_zone(zone, o.bbox):
                    ev = self._update_object(zone, o, carrier, tf, image, full)
                    if ev:
                        events.append(ev)

        events += self._expire(tf.ts)
        return events

    def finish(self) -> list:
        """End of clip: send whatever visits are still open."""
        events = []
        for key, v in list(self.person_visits.items()):
            events += self._close_person(key, v, "clip_end")
        for key, v in list(self.object_visits.items()):
            if not v.sent:
                self.skipped.append(Skipped(v.track_id, v.zone.name, f"object in exit zone only {v.unattended_seconds:.1f} s "
                                            f"unattended (< {EXIT_SECONDS:g} s)", v.last_ts - v.first_ts))
            del self.object_visits[key]
        return events

    # ---- person path -----------------------------------------------------------

    def _carriers(self, people: list[Track], objects: list[Track]) -> dict[int, int]:
        out = {}
        for o in objects:
            if o.class_name not in CARRIED_CLASSES or box_area(o.bbox) == 0:
                continue
            best, share = None, 0.0
            for p in people:
                s = intersection(o.bbox, p.bbox) / box_area(o.bbox)
                if s > share:
                    best, share = p.track_id, s
            if best is not None and share >= ATTACH_OVERLAP:
                out[o.track_id] = best
        return out

    def _update_person(self, zone, p: Track, people, objects, carrier, tf, image, full):
        key = (zone.name, p.track_id)
        v = self.person_visits.get(key)
        if v is None:
            v = self.person_visits[key] = Visit(p.track_id, "person", zone, tf.ts, tf.ts)
        v.last_ts, v.frames = tf.ts, v.frames + 1
        if v.sent:
            return

        H = full.shape[0]
        height_px = (p.bbox[3] - p.bbox[1]) * H
        cut = p.bbox[0] < 0.01 or p.bbox[1] < 0.01 or p.bbox[2] > 0.99 or p.bbox[3] > 0.99
        overlap = max((iou(p.bbox, q.bbox) for q in people if q.track_id != p.track_id), default=0.0)
        # cheap pre-score without sharpness; only crop when it could make the top list
        pre = 0.5 * min(height_px, 600) / 600 + (0.0 if cut else 0.2) - 0.3 * overlap + 0.3
        worst = min((c.score for c in v.candidates), default=-1)
        if len(v.candidates) >= CROPS_PER_VISIT and pre <= worst:
            pass
        else:
            sharp = sharpness(crop_full(full, p.bbox, pad=0.0))  # measure sharpness on the person, without the outline
            crop = crop_full(full, p.bbox, outline=True)
            score = 0.5 * min(height_px, 600) / 600 + 0.3 * min(sharp / 300, 1.0) + (0.0 if cut else 0.2) - 0.3 * overlap
            cand = Candidate(tf.ts, tf.frame_index, list(p.bbox), crop, round(score, 3),
                             {"height_px": int(height_px), "sharpness": int(sharp), "cut_off": cut,
                              "overlap_iou": round(overlap, 2), "conf": p.conf})
            self._keep_best(v, cand, image, tf)

        # close-ups of things this person carries
        for o in objects:
            if carrier.get(o.track_id) != p.track_id:
                continue
            v.attached_frames[o.track_id] = v.attached_frames.get(o.track_id, 0) + 1
            size = box_area(o.bbox) * full.shape[0] * full.shape[1]
            score = size * o.conf
            prev = v.attached.get(o.track_id)
            if prev is None or score > prev.score:
                v.attached[o.track_id] = Candidate(tf.ts, tf.frame_index, list(o.bbox), crop_full(full, o.bbox, pad=0.25, max_side=512),
                                                   score, {"width_px": int((o.bbox[2] - o.bbox[0]) * full.shape[1]),
                                                           "height_px": int((o.bbox[3] - o.bbox[1]) * full.shape[0]),
                                                           "conf": o.conf})
                v.attached_cls[o.track_id] = o.class_name

    def _keep_best(self, v: Visit, cand: Candidate, image, tf):
        # Keep the best CROPS_PER_VISIT, at least MIN_CROP_GAP apart in time.
        close = [c for c in v.candidates if abs(c.ts - cand.ts) < MIN_CROP_GAP]
        if close:
            if cand.score <= max(c.score for c in close):
                return
            v.candidates = [c for c in v.candidates if c not in close]
        if self.draw_context:
            cand.context = self.draw_context(image, tf, cand.bbox)
        v.candidates.append(cand)
        v.candidates.sort(key=lambda c: -c.score)
        del v.candidates[CROPS_PER_VISIT:]

    def _close_person(self, key, v: Visit, trigger: str) -> list:
        events = []
        if not v.sent:
            seconds = v.last_ts - v.first_ts
            best_h = max((c.metrics["height_px"] for c in v.candidates), default=0)
            if seconds < MIN_VISIT_SECONDS or v.frames < MIN_VISIT_FRAMES:
                self.skipped.append(Skipped(v.track_id, v.zone.name, f"visit too short ({seconds:.1f} s, {v.frames} frames)", seconds))
            elif best_h < MIN_PERSON_HEIGHT_PX:
                self.skipped.append(Skipped(v.track_id, v.zone.name, f"person too small ({best_h} px tall)", seconds))
            else:
                v.sent = True
                if len(v.candidates) > 1:
                    a, b = v.candidates[0], v.candidates[1]
                    if b.score < SECOND_CROP_MIN * a.score or b.metrics["height_px"] < SECOND_CROP_MIN * a.metrics["height_px"]:
                        del v.candidates[1:]
                v.attached = {t: c for t, c in v.attached.items() if v.attached_frames.get(t, 0) >= MIN_ATTACHED_FRAMES}
                events.append(PersonEvent(v, trigger))
        if trigger != "max_wait":
            del self.person_visits[key]
        return events

    # ---- object path -----------------------------------------------------------

    def _update_object(self, zone, o: Track, carrier, tf, image, full):
        key = (zone.name, o.track_id)
        v = self.object_visits.get(key)
        if v is None:
            v = self.object_visits[key] = Visit(o.track_id, o.class_name, zone, tf.ts, tf.ts)
        v.last_ts, v.frames = tf.ts, v.frames + 1
        if o.track_id in carrier:  # someone is holding it: not an obstruction, pause the timer
            v.last_unattended_ts = None
            return None
        if v.last_unattended_ts is not None:
            v.unattended_seconds += min(tf.ts - v.last_unattended_ts, GRACE_SECONDS)
        v.last_unattended_ts = tf.ts
        if v.unattended_seconds >= EXIT_SECONDS and not v.sent:
            v.sent = True
            xs = [p[0] for p in zone.polygon]
            ys = [p[1] for p in zone.polygon]
            zone_box = [max(0, min(xs)), max(0, min(ys)), min(1, max(xs)), min(1, max(ys))]
            ctx = self.draw_context(image, tf, o.bbox) if self.draw_context else image
            v.candidates = [Candidate(tf.ts, tf.frame_index, list(o.bbox), crop_full(full, o.bbox, pad=0.3, max_side=512),
                                      o.conf, {"width_px": int((o.bbox[2] - o.bbox[0]) * full.shape[1]),
                                               "height_px": int((o.bbox[3] - o.bbox[1]) * full.shape[0]), "conf": o.conf})]
            return ExitEvent(v, crop_full(full, zone_box, pad=0.0, max_side=1024), v.candidates[0].crop, ctx)
        return None

    # ---- housekeeping ----------------------------------------------------------

    def _expire(self, now: float) -> list:
        events = []
        for key, v in list(self.person_visits.items()):
            if now - v.last_ts > GRACE_SECONDS:
                events += self._close_person(key, v, "left_zone")
            elif not v.sent and now - v.first_ts >= MAX_WAIT:
                events += self._close_person(key, v, "max_wait")
        for key, v in list(self.object_visits.items()):
            if now - v.last_ts > GRACE_SECONDS:
                if not v.sent and v.unattended_seconds > 0:
                    self.skipped.append(Skipped(v.track_id, v.zone.name, f"{v.cls} left exit zone after "
                                                f"{v.unattended_seconds:.1f} s unattended (< {EXIT_SECONDS:g} s)",
                                                v.last_ts - v.first_ts))
                del self.object_visits[key]
        return events
