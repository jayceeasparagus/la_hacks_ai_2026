# PolicyLens

Program cameras with a venue policy written in plain English. Local detection,
tracking, zones and duration checks produce evidence-backed alerts for human
review. Gemini compiles policies and verifies selected uncertain crops.

Inspired by HawkWatch's camera-to-incident product loop; PolicyLens focuses on
user-defined policies, deterministic temporal rules and operator decisions.

## Implemented checkpoint: contracts and temporal replay

- Approved shared Pydantic models: `backend/app/models.py`.
- HTTP, WebSocket and integration agreements: `contracts/api.md`.
- Generated JSON schemas and validated demo payloads: `contracts/models.schema.json`
  and `contracts/examples.json`.
- Normalized zone geometry, with polygon configuration validation.
- A camera-local persistent-object engine: duration thresholds, one alert per
  incident, 1 s detection grace, 2 s closure, conservative tracking-ID recovery,
  source-relative timestamps and detection confidence averaged over observations.
- Deterministic synthetic tracking scenarios and a replay command.

The current engine supports persistent bags/chairs. Enabled attribute rules for
its camera explicitly raise `NotImplementedError` until the next increment adds
verification scheduling. Offline replay alerts have evidence marked unavailable;
they do not imply saved images or clips. The HTTP server, storage, camera workers,
vision, AI providers and frontend are not implemented in this checkout yet.

All development is on `person4-integration`. Commits and pushes are handled by
the repository collaborator. Do not commit `.env`, virtual environments, generated
evaluation tracks, Python caches, or operating-system metadata.

## Setup

Use Python 3.11 or newer. From the repository root:

```sh
python3.11 -m venv backend/.venv
source backend/.venv/bin/activate
python -m pip install -r backend/app/requirements.txt
cd backend
```

Only Pydantic v2 is required for this checkpoint. No camera, Gemini key, model
download or network access is needed after dependency installation.

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
`zones` and `rules` arrays. A config enabling attribute rules is not supported yet.
Replays use deterministic IDs and placeholder UTC times anchored to 1970-01-01;
the `ts` values remain actual positions in the source data. Live timestamps will
be recorded at incident creation.

`exit_bag` should alert once at 5.0 s. `dropout` should also alert once at 5.0 s
despite a 0.6 s missing-detection interval. `reentry` alerts at 5.0 s and 16.0 s
with different incident IDs. `threshold_dropout` waits for an observed frame at
5.4 s; it cannot alert from missing frames at the threshold.

Synthetic files sample at 10 Hz and test code behavior, not model accuracy.
See `eval/synthetic-results.md` for the checkpoint's measured test results.

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

Next: asynchronous attribute verification with a stub provider first, evidence
and SQLite storage, then FastAPI and independent fake camera workers. Integrate
teammates' real modules after the boundaries work with test substitutes.

## Limitations and evaluation

No detection accuracy, real-camera throughput, Gemini latency or end-to-end
performance has been measured. No recorded footage exists in this checkout yet.
Synthetic success does not establish that the detector can see bags or cameras.

Possible obstruction means a tracked object's bottom-center lies in a user-drawn
region; it does not establish physical passability. Timers bridge brief detection
gaps as a documented heuristic. Tracking-ID recovery is conservative and can miss
identity changes in crowded scenes. Attribute verdicts will require human review.
