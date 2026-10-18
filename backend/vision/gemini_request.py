"""Build the exact Gemini requests the hybrid design would send, without sending them.

Each request is saved as a folder: the images Gemini would get plus request.json
(prompt, response schema, metadata, status "not sent"). The verifier (Person 2)
would send the same prompt + images and validate the reply against the schema.

The questions below are a TEST POLICY standing in for compiled rules: the demo
rules (clear bags only, no professional cameras) plus the hard-hat twist.
"""

import json
from pathlib import Path

import cv2

from vision.evidence import ExitEvent, PersonEvent

# question id -> (question text, allowed answers). Every answer also gets confidence + evidence.
PERSON_QUESTIONS = {
    "clear_bag": ("If this person carries any bag, is every bag clear/transparent so its contents are visible?",
                  ["all_clear", "has_opaque_bag", "no_bag", "not_visible"]),
    "pro_camera": ("Is this person carrying a professional camera (detachable lens, DSLR/mirrorless or video "
                   "camera)? A phone does not count.", ["yes", "no", "not_visible"]),
    "helmet": ("Is this person wearing a hard hat / safety helmet?", ["yes", "no", "not_visible"]),
    "vest": ("Is this person wearing a high-visibility safety vest?", ["yes", "no", "not_visible"]),
}

PERSON_PROMPT = """You are checking one person at a venue entrance for an operator-defined policy.
The images are crops of the SAME person at different moments{closeups}.
Answer each question only from what is visible. Do not guess: if the relevant part of the
person is hidden, cut off, too small or blurry, answer "not_visible".
Do not identify the person or describe their face, age, gender or ethnicity.

Questions:
{questions}

Reply with JSON only, matching this schema:
{schema}"""

EXIT_PROMPT = """Image 1 shows the area in front of an emergency exit, as seen by a fixed camera.
Image 2 is a close-up of an object our detector found sitting in that area for {seconds:.1f} seconds
(detector label: "{label}").
Is the path to the exit blocked or narrowed by an object placed there (bag, box, chair, cart, etc.)?
People standing or walking do not count. If the view is unclear, answer "not_visible".

Reply with JSON only, matching this schema:
{schema}"""


def _answer_schema(answers: list[str]) -> dict:
    return {"type": "object", "required": ["answer", "confidence", "evidence"],
            "properties": {"answer": {"enum": answers},
                           "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                           "evidence": {"type": "string", "description": "a few words on what you saw"}}}


def person_schema() -> dict:
    return {"type": "object", "required": list(PERSON_QUESTIONS),
            "properties": {q: _answer_schema(a) for q, (_, a) in PERSON_QUESTIONS.items()}}


def exit_schema() -> dict:
    return {"type": "object", "required": ["blocked"],
            "properties": {"blocked": _answer_schema(["blocked", "partially_blocked", "clear", "not_visible"])}}


def _save(img, path: Path) -> dict:
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return {"file": path.name, "width": int(img.shape[1]), "height": int(img.shape[0])}


def write_person_request(ev: PersonEvent, out: Path, clip: str, camera_id: str, request_id: str) -> dict:
    v = ev.visit
    folder = out / request_id
    folder.mkdir(parents=True, exist_ok=True)
    images = []
    for i, c in enumerate(v.candidates, 1):
        meta = _save(c.crop, folder / f"person_{i}.jpg")
        images.append({**meta, "role": f"person crop {i}", "ts": c.ts, "score": c.score, **c.metrics})
    closeups = sorted(v.attached.items(), key=lambda kv: -kv[1].score)[:2]
    for i, (tid, c) in enumerate(closeups, 1):
        meta = _save(c.crop, folder / f"object_{i}.jpg")
        images.append({**meta, "role": f"close-up of carried {v.attached_cls[tid]} #{tid}", "ts": c.ts, **c.metrics})
    if v.candidates and v.candidates[0].context is not None:
        cv2.imwrite(str(folder / "context.jpg"), v.candidates[0].context, [cv2.IMWRITE_JPEG_QUALITY, 80])

    questions = "\n".join(f'- "{q}": {text} Answers: {", ".join(a)}.' for q, (text, a) in PERSON_QUESTIONS.items())
    closeup_note = (", followed by close-ups of item(s) the detector saw them carrying" if closeups else "")
    req = {
        "request_id": request_id, "kind": "person_attributes", "status": "NOT SENT (no Gemini key yet)",
        "clip": clip, "camera_id": camera_id, "zone": v.zone.name, "track_id": v.track_id, "trigger": ev.trigger,
        "visit": {"start_ts": round(v.first_ts, 2), "end_ts": round(v.last_ts, 2),
                  "seconds": round(v.last_ts - v.first_ts, 2), "frames": v.frames},
        "detector_saw_carrying": [v.attached_cls[t] for t, _ in closeups],
        "images": images,
        "prompt": PERSON_PROMPT.format(closeups=closeup_note, questions=questions,
                                       schema=json.dumps(person_schema(), indent=1)),
        "response_schema": person_schema(),
    }
    (folder / "request.json").write_text(json.dumps(req, indent=2), encoding="utf-8")
    return req


def write_exit_request(ev: ExitEvent, out: Path, clip: str, camera_id: str, request_id: str) -> dict:
    v = ev.visit
    folder = out / request_id
    folder.mkdir(parents=True, exist_ok=True)
    c = v.candidates[0]
    images = [{**_save(ev.zone_crop, folder / "exit_area.jpg"), "role": "exit zone area"},
              {**_save(ev.object_crop, folder / "object_1.jpg"), "role": f"close-up of {v.cls} #{v.track_id}", **c.metrics}]
    cv2.imwrite(str(folder / "context.jpg"), ev.context, [cv2.IMWRITE_JPEG_QUALITY, 80])
    req = {
        "request_id": request_id, "kind": "exit_confirmation", "status": "NOT SENT (no Gemini key yet)",
        "clip": clip, "camera_id": camera_id, "zone": v.zone.name, "track_id": v.track_id, "trigger": "timer_reached",
        "visit": {"start_ts": round(v.first_ts, 2), "end_ts": round(v.last_ts, 2),
                  "seconds_unattended": round(v.unattended_seconds, 2), "frames": v.frames},
        "detector_label": v.cls,
        "images": images,
        "prompt": EXIT_PROMPT.format(seconds=v.unattended_seconds, label=v.cls, schema=json.dumps(exit_schema(), indent=1)),
        "response_schema": exit_schema(),
    }
    (folder / "request.json").write_text(json.dumps(req, indent=2), encoding="utf-8")
    return req
