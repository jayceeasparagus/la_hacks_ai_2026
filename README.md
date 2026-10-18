# PolicyLens

Program cameras with a venue policy written in plain English. Local detection,
tracking, zones and duration checks produce evidence-backed alerts for human
review. Gemini compiles policies and verifies selected uncertain crops.

Inspired by HawkWatch's camera-to-incident product loop; PolicyLens focuses on
user-defined policies, deterministic temporal rules and operator decisions.

## What works in this checkout

- **Policy compiler** (`backend/policy/`, Person 2): plain English to validated rule
  cards, honest `unsupported` notes, an offline fallback for the demo prompt, a
  compile cache, and a Gemini circuit breaker.
- **Crop verifier** (`backend/verify/`, Person 2):
  - checks: clear bag, professional camera, hard hat, hi-vis vest
  - 4 s budget, never raises, shared rate limit
- **Temporal engine** (`backend/engine/`):
  - "stays too long" rules: duration thresholds, one alert per incident, 1 s
    detection grace, 2 s closure, conservative tracking-ID recovery
  - attribute rules: one verification per incident on the best crop, then a
    violation, compliant or manual-review result
  - one shared bounded verification queue: 2 workers, 8 pending jobs, 2 starts/s,
    4 s timeout; reconnects invalidate old-session results
- **Server** (`backend/app/main.py`): every route and WebSocket message in
  `contracts/api.md`.
  - one worker thread per camera (max 3)
  - MJPEG stream and snapshots
  - SQLite alerts with a decision audit trail
  - JSON settings
  - evidence JPEG plus a ~4 s clip, with bounded encoding and frame buffers
  - verification results delivered even while capture waits for another frame
  - late evidence updates preserve operator decisions; slow WebSocket clients
    reconnect with code 1013 if their queue would lose an alert
- **Camera sources:**
  - `synthetic:<scene>` and `replay:<tracks.jsonl>` work out of the box.
  - `webcam:N`, `url:...` and `clip:...` use Person 1's vision pipeline. Until
    `person1/vision` is merged and its detector stack installed, they show
    `offline` with an explanation.
- **Eval** (`eval/run_eval.py`): correct, false, missed and duplicate alerts, plus
  latency per labeled case. `eval/recorded_eval.py` additionally checks 20 saved-video
  cases with explicitly canned verdicts and reports execution errors.

Contracts live in `backend/app/models.py` and `contracts/api.md`. The schemas and
demo payloads are generated into `contracts/`. Construction-site safety gear
(`hard_hat`, `safety_vest` on `person`) is part of the contract.

## Setup

Use Python 3.11 or newer. From the repository root:

```sh
python3.11 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -r backend/app/requirements.txt
```

Put Gemini settings in `.env` at the repository root (never commit it):

```sh
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-flash-latest
```

Without a key, or with `POLICYLENS_FAKE_LLM=1`:
- the compiler uses its offline fallback
- the verifier answers deterministically from image brightness

That's good for development and tests, not for real verdicts.

## Run

From `backend/`:

```sh
# Full demo with no camera and no Gemini key: two synthetic cameras, demo zones and rules
POLICYLENS_SEED_DEMO=1 POLICYLENS_DEMO_SOURCES=synthetic POLICYLENS_FAKE_LLM=1 uvicorn app.main:app --port 8000

# Normal run (cameras, zones and policy are configured through the API or UI)
uvicorn app.main:app --port 8000
```

Data (settings, `alerts.db`, evidence) goes to `POLICYLENS_DATA_DIR`, default `backend/data/`, which
is git-ignored.

In the synthetic demo:
- `cam_exit` shows a backpack left in the emergency exit. That gives an urgent
  "Possible exit obstruction" alert after 5 s.
- `cam_entrance` shows an opaque backpack, then a clear handbag. That gives one
  "Possible non-clear bag" review alert.

## Tests and eval

From `backend/`:

```sh
POLICYLENS_FAKE_LLM=1 python -B -m pytest app/tests engine/tests store/tests policy/tests verify/tests ../eval/tests -q
python -m pytest policy/tests verify/tests -m live -s  # live Gemini; needs GEMINI_API_KEY
python -B -m engine.fake_tracks ../eval/generated
python -B ../eval/run_eval.py ../eval/cases.csv
python -B -m engine.replay ../eval/generated/exit_bag.tracks.jsonl
```

From the repository root, the recorded fixtures and continuous check are:

```sh
python -B eval/generate_fixtures.py
python -B eval/recorded_eval.py --output eval/generated/recorded-report.json
python -B eval/soak_backend.py --output eval/generated/soak-report.json
```

The soak defaults to five minutes. `--seconds 20` runs a shorter wiring check.
`eval/cases.csv` remains main's track/vision evaluation format;
`eval/recorded_cases.csv` is the separate saved-video/canned-verdict format.
Generated clips and reports are git-ignored. See `eval/backend-results.md`.

To check the server end to end: start the synthetic demo above, then
`POST /api/policy/compile` with the demo prompt, `POST /api/monitor/start`, and
`GET /api/alerts`.

To regenerate the machine-readable contracts from the models:

```sh
python -B -m app.export_contracts ../contracts
```

## Results so far

| What | Result | Source |
| --- | --- | --- |
| Synthetic engine scenarios | 12/12 pass | `eval/synthetic-results.md` |
| Synthetic eval cases | 8/8 expected alerts correct, 0 false, 0 missed, 0 duplicates | `eval/run_eval.py` |
| Synthetic live server | 10 fps per camera; 15–47 ms from frame to stored alert | server log |
| Recorded synthetic video | 20/20 cases, 17 matched alerts, 0 false/missed/duplicate | `eval/recorded_eval.py` |
| Real clips: detection, false alerts, latency | **not measured yet**, no footage recorded | — |
| Gemini compile latency and verifier accuracy | **not measured yet**, no API key | `verify.eval` once crops exist |

## Architecture

```text
Organizer prompt -> policy compiler (Gemini + checks) -> rule cards -> operator confirms
Camera -> vision pipeline (YOLO-World + ByteTrack) -> contract adapter -> rule engine
  -> crop verifier (Gemini, one call per incident) -> alert
  -> evidence writer + SQLite -> FastAPI REST / WebSocket / MJPEG -> UI
  -> human review decision -> audit record
```

## Limitations

- **No real footage has been measured yet.** Synthetic success doesn't show the
  detector can see bags, cameras or helmets.
- **"Possible obstruction"** means a tracked object's bottom-center is inside a
  user-drawn region. It doesn't establish physical passability.
- **Timers** bridge brief detection gaps as a documented heuristic.
- **Tracking-ID recovery** is conservative and can miss identity changes in
  crowded scenes.
- **Attribute verdicts are hedged and always go to a human.** "Unclear" becomes a
  manual-review alert, never a confirmed violation.
- **PolicyLens never identifies people.** Each person is an anonymous track within
  one camera, with no face recognition and no cross-camera re-identification.
- **Evidence clips** use H.264 when the platform's OpenCV build supports it, and
  otherwise fall back to `mp4v`, which some browsers can't play.
