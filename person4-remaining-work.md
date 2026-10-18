# Person 4: remaining work

Written 2026-10-17 from a review of `origin/person4-integration` at `7716800`, with
`origin/person1/vision` and `origin/person2-policy-ai` for the interfaces it has to connect.
`CLAUDE.md` and `contracts/api.md` remain the source of truth. This file lists what is still
missing, in the order the demo needs it.

## Where things stand

**Done and tested** (37 unittest tests pass, re-run 2026-10-17):

- Approved models in `backend/app/models.py`, plus `contracts/api.md`, `models.schema.json` and
  `examples.json`.
- Zone geometry and polygon validation (`engine/zones.py`).
- `RuleEngine` for `persistent_object` rules:
  - duration thresholds and one alert per incident
  - 1 s detection grace and 2 s closure
  - tracking-ID recovery
  - independent cameras
- `engine/fake_tracks.py`, `engine/replay.py`, and 12 synthetic scenarios, all passing.

**Not started:** attribute rules, evidence, the FastAPI server, storage, camera workers,
real-clip eval, and the full dependency list.

**Team context:**

- Nothing is merged into `main` yet.
- No frontend branch is on GitHub.
- No recorded clips exist on any branch.

## Priority order

| # | Task | Why it matters | Blocks |
| --- | --- | --- | --- |
| 1 | Attribute rules in `RuleEngine` | The clear-bag and camera demo beats | Demo, eval |
| 2 | Adapter from Person 1's TrackFrame to the approved models | Live cameras can't feed the engine without it | Live demo |
| 3 | FastAPI app, storage and camera workers | Nothing is usable from the UI without it | Person 3, demo |
| 4 | Evidence (JPEG + clip) | "Evidence-backed alerts" is the pitch | Review screen |
| 5 | Real-clip eval and README | Judges' numbers | Submission |
| 6 | Stretch goals | Only after the definition of done passes | — |

---

## 1. Attribute rules in `RuleEngine` (P0)

Right now `RuleEngine.__init__` raises `NotImplementedError('Attribute verification is the next increment')`
for any enabled `object_attribute` rule on its camera. That stops the demo policy from even loading.

### Behavior (from `CLAUDE.md`, the Person 4 brief and `contracts/api.md`)

1. A tracked object of one of `rule.objects` is in `rule.zone` for `rule.duration_seconds`
   (default 1 s). Reuse the timing and grace logic from persistent rules.
2. Pick the track's **best crop** so far: a large box with high confidence. Keep the best
   `(score, frame, bbox)` per incident while timing. The `frame` argument of `update()` is
   already reserved for this.
3. Submit **one verification per incident** (per track) to a `ThreadPoolExecutor`. Never
   block `update()`.
   ```python
   from verify.verifier import verify_crop
   from verify.prompts import CHECK_FOR_ATTRIBUTE   # {"transparent": "transparent_bag", "professional": "professional_camera"}
   from vision.pipeline import crop                 # Person 1: crop(frame, bbox, pad=0.15) -> BGR array

   check = CHECK_FOR_ATTRIBUTE[rule.attribute.name]
   future = executor.submit(verify_crop, crop(frame, bbox), check)
   ```
4. Each `update()` polls finished futures (and replay drains them at the end):

   | `verdict.answer` | Meaning | Result |
   | --- | --- | --- |
   | `== rule.attribute.expected` | Compliant (clear bag, or a phone) | No alert. Phase `compliant`, and the incident stays deduplicated |
   | `!= rule.attribute.expected` (not None) | Violation | Alert, severity `rule.severity`, confidence `verdict.confidence` |
   | `None` | Couldn't tell | **Manual review** alert saying we couldn't tell, with `verdict.reason` |

5. While waiting, emit `RuleState` with phase `verifying`.
6. `reset()` (rewind or reconnect) must **invalidate pending jobs**. Tag each job with
   `session_id` and drop results from an old session (`api.md` convention 3).

### What Person 2's `verify_crop` guarantees (`backend/verify/CLAUDE.md`)

- It never raises and never retries. It returns within about 4 s, including up to 1 s waiting
  for its own rate limiter.
- It enforces the global limit itself: 2 calls/s and at most 4 in flight, shared by all camera
  threads. Your scheduler can stay simple. A second limiter is harmless but not needed.
- Fixed reasons when there is no model answer: `"object too small to judge"` (a side under
  40 px), `"verification busy"`, `"verification timed out"` and `"verification unavailable"`.
  **Suggestion:** treat `"verification busy"` as *retry once after about 1 s* rather than raising
  a manual-review alert straight away. Busy only means the limiter was full.
- `POLICYLENS_FAKE_LLM=1` gives deterministic offline verdicts for your tests: bright crops
  (mean ≥ 128) are clear bags, and dark crops (mean < 100) are professional cameras.

### Alert wording (hedged, measured facts only)

| Case | `title` | `observation` example |
| --- | --- | --- |
| Opaque bag | "Possible non-clear bag" | "A backpack in the Main entrance zone is probably not a clear bag (Gemini: black fabric backpack)." |
| Pro camera | "Possible professional camera" | "A camera in the Main entrance zone looks like a professional-style camera (Gemini: DSLR with long lens)." |
| Unclear | "Manual review needed" | "Couldn't tell whether the backpack in the Main entrance zone is a clear bag (verification timed out)." |

**Bug to fix while you're in `alerts.py`:** `obstruction_alert` hard-codes
`title='Possible exit obstruction'` for every persistent rule. A rule like "Unattended bag" at a
stage door would then read as an exit obstruction. Derive the title from the rule or zone, for
example `f"Possible {rule.name.lower()}"`.

### Tests to add

- A clear bag (fake verdict True): 0 alerts.
- An opaque bag: 1 alert.
- An unclear verdict: 1 manual-review alert.
- A bag in the zone for less than `duration_seconds`: 0 verify calls.
- One verify call per track, even over 300 frames.
- Reset during a pending verify: the stale result is ignored.
- Two cameras: verdicts tagged to the right camera.
- `engine.replay --config` with the demo rules (`app/demo.py` already has them).

---

## 2. Adapter from Person 1's TrackFrame (P0 for live cameras)

`origin/person1/vision` still uses a **draft dataclass** `vision/trackframe.py`, not
`app.models.TrackFrame`. The field names differ, and the approved models use `extra='forbid'`.

| Person 1 draft | Approved `app.models` | Action |
| --- | --- | --- |
| `Track.class_name` | `Track.object_class` | rename |
| `Track.conf` | `Track.confidence` | rename |
| `Track.bbox: list` | `BBox` tuple in [0, 1], `x1 < x2` and `y1 < y2` | clamp, then **drop** degenerate boxes (the validator raises) |
| `TrackFrame.frame_index`, `width`, `height` | not in the model | drop (extra fields are forbidden) |
| `ts`: **unix time** for live cameras | monotonic seconds since session start | subtract the session start time |

Either Person 1 switches to `app.models` after the merge (simplest), or you add
`vision_to_contract(tf) -> TrackFrame` in `backend/app/`. Agree on one.

Other points:

- `RuleEngine.update()` raises if `ts` doesn't strictly increase. Person 1's `CameraRunner`
  rebuilds the pipeline after an error, so frame `ts` can go backwards. The worker must call
  `engine.reset()` on every pipeline restart.
- Person 1 exposes `CameraRunner(..., on_frame=callback)`, `status`, `fps`, `latest()`,
  `VisionPipeline.recent_frames(seconds)` and `crop(frame, bbox, pad=0.15)`. Reuse these
  rather than writing a second capture loop.

---

## 3. FastAPI app, storage and camera workers (P0)

Nothing in Part B exists yet. Suggested layout, all inside your folders:

```
backend/app/main.py        # FastAPI app, routes, /ws, /evidence, startup/shutdown
backend/app/workers.py     # one thread per camera: pipeline -> engine -> store -> broadcast
backend/app/settings.py    # cameras/zones/policy JSON load+save (validated before writing)
backend/app/broadcast.py   # WebSocket fan-out that never blocks workers
backend/store/db.py        # SQLite: alerts + decision audit
```

### Routes (every one in `contracts/api.md`)

| Route | Notes |
| --- | --- |
| `GET /api/health` | `{status: "ok"}`. Optionally add `policy.llm.status()` (mode, models, key set, Gemini paused). That needs a contract note. |
| `GET/PUT /api/cameras` | At most 3 cameras. Reject with 409 while monitoring. Strip credentials from URLs in errors and logs. |
| `GET /api/snapshot/{camera_id}` | Latest JPEG, used for drawing zones. 503 if the camera is offline. |
| `GET /api/stream/{camera_id}` | MJPEG of the latest **annotated** frame. Person 1 has `vision/annotate.py`. |
| `GET/PUT /api/zones` | Validate polygons with `engine.zones.validate_polygon`. Reject unknown cameras. |
| `POST /api/policy/compile` | `compile_policy(prompt, saved_zones)` from `policy.compiler`. It's blocking, so use a plain `def` route (threadpool) or `run_in_threadpool`. It never raises and returns within about 15 s. It **does not activate** rules. |
| `GET/PUT /api/policy` | PUT validates `{rules: Rule[]}` against the saved zones, then activates. 409 while monitoring. |
| `POST /api/monitor/start` / `stop`, `GET /api/monitor` | Idempotent. Build one `RuleEngine` per camera from the saved zones and rules. |
| `GET /api/alerts`, `GET /api/alerts/{id}` | Filters: `camera_id`, `status`, `limit`, `offset`. Returns `{alerts, total}`. |
| `POST /api/alerts/{id}/decision` | `confirmed`, `dismissed` or `unclear`. Marks the alert reviewed, writes an audit row, and repeating it is idempotent. Broadcast `alert_updated`. |
| `GET /evidence/{filename}` | Generated basenames only. Reject `..` and slashes. |

Errors: 422 for unknown fields or invalid values (Pydantic does this), 404 for missing
resources, 409 for conflicts or changes while monitoring.

### WebSocket `/ws`

- On connect, send `snapshot` (`running`, camera statuses, current rule states).
- Then send `camera_status`, `state` (a full per-camera replacement, throttled for the UI),
  `alert`, `alert_updated` and `monitor_status`.
- Give each client its own bounded queue and drop old `state` messages when it's full. A slow
  browser must never stall a camera thread.

### Camera workers

- One thread per camera:
  `CameraRunner/VisionPipeline -> adapter -> RuleEngine.update -> store new alerts -> broadcast`.
- **Nothing in the loop may kill it:** wrap each iteration, log, continue.
- On a camera drop: status `offline`, reconnect, `engine.reset()`. The other cameras keep running.
- Start and stop are safe to call twice.
- Log per camera: FPS, and alert latency (frame `ts` to alert stored). Gemini latency is
  logged by Person 2's code.

### Storage

- **SQLite (`store/db.py`):**
  - an `alerts` table: id, camera_id, rule_id, severity, status, decision, created_at, and the
    full Alert JSON
  - a `decisions` table: alert_id, decision, decided_at (append-only audit)
- **JSON settings:** `cameras.json`, `zones.json`, `policy.json`, written atomically (write a
  temp file, then rename).

### Environment and startup

- Call `load_dotenv()` at startup, so `GEMINI_API_KEY`, `GEMINI_MODEL` and
  `POLICYLENS_FAKE_LLM` are read. Person 2's modules don't load `.env` themselves.
- **Dependencies:** `backend/app/requirements.txt` lists only pydantic. Add fastapi,
  uvicorn[standard], numpy, opencv-python, ultralytics, google-genai and python-dotenv. Keep one
  requirements file for the backend.

---

## 4. Evidence (P1)

Every alert currently has `evidence_status='unavailable'`. Per `api.md` convention 8:

1. Create the alert immediately with `evidence_status='pending'`. An urgent alert must not wait
   for encoding.
2. In a background thread:
   - Save a JPEG of the alert frame with the bbox and label drawn.
   - Save an MP4 of about the last 4 s from `VisionPipeline.recent_frames(4.0)`.
   - Write both to an evidence directory with generated basenames.
3. Update the same alert to `ready` (with `evidence_image_url` and `evidence_clip_url`) or
   `unavailable`, store it, and broadcast `alert_updated`.
4. Replays with no frames keep `unavailable`, as they do today.

---

## 5. Real-clip eval and README (P1, Part C)

- **Clips needed first:** record them as a team. One session also gives Person 2 the labeled
  crops for `verify.eval`. Suggested clips:

  | Clip | Purpose |
  | --- | --- |
  | bag left in the exit zone for 8 s | should alert once |
  | person walking through the exit | should not alert |
  | bag placed for 3 s, then removed | should not alert |
  | clear bag at the entrance | should not alert |
  | opaque bag at the entrance | should alert |
  | DSLR at the entrance | should alert |
  | phone at the entrance | should not alert |
  | two cameras running at once | both work |

- `eval/cases.csv`: `clip, camera_id, rule_id, expected_alerts, window_start_s, window_end_s`.
- `eval/run_eval.py`: run the full pipeline on each clip at maximum speed. Print correct
  detections, false alerts, missed events, duplicate alerts and mean alert latency.
- README:
  - architecture diagram (already there)
  - how to run all three services
  - the real eval table next to the synthetic one
  - Gemini latency and verifier accuracy, from Person 2
  - limitations
  - HawkWatch credit (already there)
- Also on Person 4's list: the demo video, the pitch and the checkpoint schedule.

---

## 6. Merge plan

1. Merge `person4-integration` into `main` first, since it owns the contracts.
2. Merge `person1/vision` and `person2-policy-ai`. Both merge cleanly with
   `person4-integration` (checked with `git merge-tree` on 2026-10-17).
3. After the merge:
   - Person 2 deletes the temporary model mirror in `backend/policy/contracts.py`. Their code
     then imports `app.models` automatically. It already passes all tests against your
     `models.py`, and its demo compile matches `contracts/examples.json` exactly.
   - Person 1 switches to `app.models`, or you add the adapter from section 2.
4. Run everyone's tests together from `backend/`. Person 2's tests use pytest
   (`python -m pytest policy/tests verify/tests`); yours use unittest.

---

## 7. Definition of done: what each item still needs

| Definition-of-done item (`CLAUDE.md`) | Still needs |
| --- | --- |
| Enter the demo policy without editing code; it becomes editable rule cards | §3 compile and policy routes, plus Person 3's UI |
| Draw and name at least two zones | §3 snapshot and zones routes, plus the UI |
| A clear bag doesn't alert; an opaque bag gives an evidence-backed review alert | §1, §2, §4 |
| Exit obstruction alerts only after the duration, once per incident | Done offline. Needs §2 and §3 to run live |
| Operator can confirm, dismiss or mark unclear | §3 decision route and storage, plus the UI |
| Unsupported policies give an honest warning | Done in Person 2's compiler. Needs the §3 compile route |
| 5-minute continuous demo without restarting | §3 worker robustness, then a soak test |
| Two live cameras, separate zones, alerts name their camera, one can drop | §2, §3 workers. Engine isolation is already tested |

## 8. Stretch (only after section 7 passes)

1. **Incident timeline** on each alert: entered zone, threshold reached, verified, operator
   decision.
2. **Person down:** needs a contract change. Add `lying_down` for `person` in
   `SUPPORTED_ATTRIBUTES`, and let `Attribute.name` and the Rule validator accept a persistent
   person rule with that attribute. Person 2's compiler and verifier (`person_down` check)
   already support it behind a gate that turns on automatically when the contract allows it.
