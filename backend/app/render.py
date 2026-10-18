"""Drawing for the server: synthetic camera frames and the annotated monitor view.

Synthetic frames are plain gray scenes with each track drawn as a filled box.
Bags are dark unless listed as clear, so Person 2's offline fake verifier
(POLICYLENS_FAKE_LLM=1) judges them 'not clear' and the demo produces a review alert.
"""

import cv2
import numpy as np

from app.models import Rule, RuleState, TrackFrame, Verdict, Zone
from engine.alerts import is_prohibition
from engine.zones import is_whole_frame

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
# Attribute checks drawn per object. Neutral words only: a check reports what was seen.
CHECK_LABEL = {'hard_hat': 'Hard hat', 'safety_vest': 'Hi-vis vest', 'transparent': 'Clear bag',
               'professional': 'Pro camera'}
CHECK_WORDS = {'hard_hat': ('not seen', 'yes'), 'safety_vest': ('not seen', 'yes')}  # (no, yes)
CHECK_COLOR = {'ok': (70, 160, 40), 'missing': (0, 140, 235), 'unclear': (120, 120, 120),
               'pending': (120, 120, 120)}
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


def _check(rule: Rule, state: RuleState, verdict: Verdict | None) -> tuple[str, str]:
    """(label, outcome) for one attribute check on one track: outcome is ok, missing, unclear or pending."""
    name = rule.attribute.name
    label = CHECK_LABEL.get(name, name.replace('_', ' ').capitalize())
    if state.phase in ('timing', 'verifying') or verdict is None:
        return f'{label}: checking', 'pending'
    if verdict.answer is None:
        return f'{label}: unclear', 'unclear'
    no, yes = CHECK_WORDS.get(name, ('no', 'yes'))
    text = f'{label}: {yes if verdict.answer else no}'
    return text, 'ok' if verdict.answer == rule.attribute.expected else 'missing'


def _from_center(track) -> float:
    x1, y1, x2, y2 = track.bbox
    return ((x1 + x2) / 2 - 0.5) ** 2 + ((y1 + y2) / 2 - 0.5) ** 2


def annotate(image: np.ndarray, zones: list[Zone], tf: TrackFrame | None,
             states: list[RuleState], rules: dict[str, Rule] | None = None,
             verdicts: dict[tuple[str, int], Verdict] | None = None) -> np.ndarray:
    """A copy of the frame with zones outlined, boxes labelled, active rule timers and, for
    attribute rules, each person's checks ("Hard hat: yes", "not seen", "unclear", "checking").

    Whole-frame zones aren't drawn: the camera is judged as a whole. Boxes nearest the frame
    center are drawn last, so their labels stay readable where boxes overlap.
    """
    out = np.ascontiguousarray(image, dtype=np.uint8).copy()
    if out.ndim == 2:
        out = cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)
    rules, verdicts = rules or {}, verdicts or {}
    for zone in zones:
        if is_whole_frame(zone.polygon):
            continue
        points = np.array([_px(out, x, y) for x, y in zone.polygon], np.int32)
        cv2.polylines(out, [points], True, ZONE_COLOR, 2, cv2.LINE_AA)
        _label(out, zone.name, int(points[:, 0].min()), int(points[:, 1].min()) + 2, (150, 110, 0))
    if tf is None:
        return out
    active_states: dict[int, list[RuleState]] = {}
    for state in states:
        if state.phase != 'cleared':
            active_states.setdefault(state.track_id, []).append(state)
    for track in sorted(tf.tracks, key=_from_center, reverse=True):
        p1 = _px(out, track.bbox[0], track.bbox[1])
        p2 = _px(out, track.bbox[2], track.bbox[3])
        timers, checks = [], {}
        for state in active_states.get(track.track_id, []):
            rule = rules.get(state.rule_id)
            if rule is not None and rule.type == 'object_attribute' and rule.attribute is not None:
                # One line per attribute, even if two rules check it (e.g. overlapping zones).
                checks.setdefault(rule.attribute.name,
                                  _check(rule, state, verdicts.get((state.rule_id, track.track_id))))
            else:
                timers.append(state)
        outcomes = {outcome for _, outcome in checks.values()}
        if checks:
            color = CHECK_COLOR['missing' if 'missing' in outcomes else
                                'ok' if outcomes == {'ok'} else 'unclear']
        else:
            color = PHASE_COLOR[timers[0].phase] if timers else TRACK_COLOR
        cv2.rectangle(out, p1, p2, color, 2, cv2.LINE_AA)
        # Labels sit above the box, or just inside its top when the box touches the frame edge.
        top = p1[1] if p1[1] >= 24 else p1[1] + 22
        _label(out, f'{track.object_class} #{track.track_id}', p1[0], top, (60, 60, 60))
        for row, (text, outcome) in enumerate(checks.values()):
            _label(out, text, p1[0], top + 20 * (row + 1), CHECK_COLOR[outcome])
        for row, state in enumerate(timers):
            rule = rules.get(state.rule_id)
            if rule is not None and is_prohibition(rule):
                # "No bags": the object being in view is the finding, so no timer readout.
                if state.phase != 'alerted':
                    continue
                text = f'{track.object_class.capitalize()} in view'
            else:
                name = rule.name if rule is not None else state.rule_id
                text = (f'{name} {state.elapsed_seconds:.1f}/{state.duration_seconds:g}s'
                        f' {state.phase}')
            _label(out, text, p1[0], p2[1] + 20 * (row + 1), PHASE_COLOR[state.phase])
    return out


def encode_jpeg(image: np.ndarray, quality: int = JPEG_QUALITY) -> bytes | None:
    ok, data = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return data.tobytes() if ok else None
