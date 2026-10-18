# PolicyLens

Program cameras with a venue policy written in plain English. Local detection,
tracking, zones and duration checks produce evidence-backed alerts for human
review. Gemini compiles policies and verifies selected uncertain crops.

Inspired by HawkWatch's camera-to-incident product loop; PolicyLens focuses on
user-defined policies, deterministic temporal rules and operator decisions.

## Implemented checkpoint: Part A engine, verification and evidence

- Approved shared Pydantic models: `backend/app/models.py`.
- HTTP, WebSocket and integration agreements: `contracts/api.md`.
- Generated JSON schemas and validated demo payloads: `contracts/models.schema.json`
  and `contracts/examples.json`.
- Normalized zone geometry, with polygon configuration validation.
- A camera-local persistent-object engine: duration thresholds, one alert per
  incident, 1 s detection grace, 2 s closure, conservative tracking-ID recovery,
  source-relative timestamps and detection confidence averaged over observations.
- Deterministic synthetic tracking scenarios and a replay command.
- Attribute rules with best-crop selection, session/track caching, background
  verification, a shared two-calls-per-second start limit, and four-second timeouts.
- Explicit canned-result verifier for offline work and an injectable Person 2
  verifier callable. Compliant results stay quiet; violations and unclear results
  create one review alert per incident.
- Bounded source-frame buffering, annotated JPEGs, approximately the last four
  seconds of MP4 evidence, and asynchronous completion patches.
- A recorded-video + saved-track replay command and labeled synthetic demo inputs.

The rule-engine functionality in Part A is implemented and tested offline. The
HTTP server, SQLite storage, live camera workers and full teammate integration
remain Part B work. A real Gemini provider is not included in this branch;
inject Person 2's callable after that module is available. The default verifier
is an explicitly unclear stub, never a claim of real visual classification.

All development is on `person4-integration`, with incremental implementation
commits. Push only when requested. Do not commit `.env`, virtual environments, generated
evaluation tracks, Python caches, or operating-system metadata.

## Setup

Use Python 3.11 or newer. From the repository root:

```sh
python3.11 -m venv backend/.venv
source backend/.venv/bin/activate
python -m pip install -r backend/app/requirements.txt
cd backend
```

Dependencies are Pydantic v2, NumPy and OpenCV. No camera, Gemini key, model
download or network access is needed for the offline checks after installation.

## Tests and replay

From `backend/`:

```sh
python -B -m unittest discover -v
python -B -m engine.fake_tracks ../eval/generated
python -B -m engine.replay ../eval/generated/exit_bag.tracks.jsonl
python -B -m engine.replay ../eval/generated/dropout.tracks.jsonl
python -B -m engine.replay ../eval/generated/reentry.tracks.jsonl
```

Replay prints one JSON alert per line to stdout and a summary to stderr. It uses
synthetic exit geometry unless `--config PATH` supplies a JSON object containing
`zones` and `rules` arrays. Track-only attribute replay cannot inspect images, so
eligible attribute candidates produce manual-review alerts without provider calls.
Replays use deterministic IDs and placeholder UTC times anchored to 1970-01-01;
the `ts` values remain actual positions in the source data. Live timestamps will
be recorded at incident creation.

`exit_bag` should alert once at 5.0 s. `dropout` should also alert once at 5.0 s
despite a 0.6 s missing-detection interval. `reentry` alerts at 5.0 s and 16.0 s
with different incident IDs. `threshold_dropout` waits for an observed frame at
5.4 s; it cannot alert from missing frames at the threshold.

Synthetic files sample at 10 Hz and test code behavior, not model accuracy.
See `eval/synthetic-results.md` for the earlier temporal checkpoint and
`eval/part-a-results.md` for the verification/evidence checkpoint.

## Recorded-video offline demo

From `backend/`, generate labeled synthetic video and matching saved tracks:

```sh
python -B -m engine.demo_recording ../eval/generated/part_a
```

Replay the exit scenario, which produces one alert with an annotated JPEG and a
four-second MP4:

```sh
python -B -m engine.clip_replay \
  ../eval/generated/part_a/exit.mp4 \
  ../eval/generated/part_a/exit.tracks.jsonl \
  --config ../eval/generated/part_a/config.json \
  --evidence ../eval/generated/part_a/exit-evidence
```

Replay entrance violations using **canned, not visually inferred** answers:

```sh
python -B -m engine.clip_replay \
  ../eval/generated/part_a/entrance.mp4 \
  ../eval/generated/part_a/entrance.tracks.jsonl \
  --config ../eval/generated/part_a/config.json \
  --evidence ../eval/generated/part_a/entrance-evidence \
  --stub-bag opaque --stub-camera professional
```

This produces two alerts. Use `--stub-bag clear --stub-camera ordinary` for a
zero-alert compliant replay, or leave both as `unclear` for manual-review alerts.
Entrance rules trigger at 1 s, so only one second of pre-alert footage exists;
the writer saves that available history instead of inventing a four-second clip.

The generated pictures are labeled synthetic, the CLI prints its stub mode to
stderr, and canned verdict reasons are labeled STUB. Neither input nor result
is an accuracy benchmark. Alerts print to stdout after verification and evidence
jobs finish; evidence URLs are `/evidence/<generated-basename>` for the later
HTTP server to serve from the chosen directory. They are not hosted yet.

To use real Person 2 verification once its module is present, select
`--verifier person2`. The command imports `verify.verifier.verify_crop` explicitly;
missing modules or configuration are not silently replaced with canned results.

## Integrating the background workers

Construct one shared `VerificationScheduler(verify_crop)` for all cameras and
pass it as `scheduler=` to each `RuleEngine`. Provider results are validated
against the approved Verdict model, including models from another Pydantic module.
Malformed results retry once within the same rate limit, then become unclear.
Queue saturation never blocks a frame: the engine retains the best crop and
retries submission on a later eligible observation. Cached checks are scoped by
camera, session, check type and original track ID; reset invalidates old results.

Construct one `EvidenceWriter(Path(...))` and pass it as `evidence_writer=`. Each
engine keeps its own bounded ring (up to 10 Hz, 640 px wide, 4.2 s and 32 MiB).
Verification captures its evidence window at submission, so a delayed response
cannot substitute later frames. JPEG and video encoding use separate background
workers. Initial alerts say `pending`; `engine.poll_evidence()` yields patches.
Use `patch.apply(latest_stored_alert)` before storing/broadcasting `alert_updated`;
this preserves operator decisions made while encoding was running. It does not
create a second incident. A ready patch can contain just a JPEG if video encoding
was unavailable; a failed snapshot produces `unavailable`.

Live frame loops use `update`, `poll_verifications` (also while a camera is idle)
and `poll_evidence`. At clip EOF or shutdown, collect `drain_verifications()`
before `drain_evidence()`. Only then close the shared workers. The drain helpers
block and must not run inside a live frame callback. The application layer still
needs to persist and broadcast these results.

Verification and encoding latencies are logged through Python logging; enable
INFO-level logging in the host application. A timed-out provider cannot be killed
inside a Python thread. The caller receives an unclear result promptly, while
the still-running call retains its bounded worker slot. Person 2 must also set
a network timeout, as its verifier interface specifies.

To regenerate machine-readable contracts from the approved models:

```sh
python -B -m app.export_contracts ../contracts
```

## Architecture and next increments

```text
Organizer prompt -> Person 2 compiler -> approved rules -> operator confirms
Camera -> Person 1 detector/tracker -> Person 4 temporal engine
  -> asynchronous crop verifier (Person 2)
  -> evidence + SQLite -> FastAPI / live updates -> Person 3 interface
  -> human review decision -> saved record
```

Next: SQLite alert/decision storage, FastAPI routes and independent fake camera
workers, then full teammate integration. Person 1's current branch uses its own
tracking data objects; integration will need an explicit adapter to the approved
TrackFrame shape. No teammate-owned files were changed for this checkpoint.

## Limitations and evaluation

No detection accuracy, real-camera throughput, real Gemini latency or live
end-to-end performance has been measured. Recorded synthetic inputs exercise
decoding and encoding; they are not footage of actual bags or cameras.
Synthetic success does not establish that a detector can see those objects.

Possible obstruction means a tracked object's bottom-center lies in a user-drawn
region; it does not establish physical passability. Timers bridge brief detection
gaps as a documented heuristic. Tracking-ID recovery is conservative and can miss
identity changes in crowded scenes. Attribute verdicts require human review.
