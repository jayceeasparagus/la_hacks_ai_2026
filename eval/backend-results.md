# Person 4 backend and evaluation results

Validated on 2026-10-17 on the local Mac using Python 3.12.14, Pydantic 2.14.0,
NumPy 2.3.5, OpenCV 5.0.0, FastAPI 0.143.3, Starlette 1.8.0 and httpx 0.28.1.
The project minimum is Python 3.11; that interpreter was not separately tested.

## Automated checks

- **96 backend tests pass**: shared models, geometry, temporal rules, attribute
  verification, evidence, persistence, camera workers, adapters, API and WebSocket.
- **5 evaluation-scoring tests pass**: positive/negative cases, time-window
  matching, duplicate classification and manifest validation.
- Multipart streaming returns an actual JPEG frame. Evidence video byte-range
  requests return 206 and the expected number of bytes.
- An unavailable camera retries while another camera produces and saves an
  alert. Repeated start/stop and restart are tested.
- Configuration references and polygons are validated before persistence; disk
  replacement failure preserves previous settings. Review and evidence updates
  are serialized in SQLite so one cannot overwrite the other.

## Twenty recorded functional cases

`eval/cases.csv` references generated, visibly synthetic clips and saved tracks.
Entrance cases reuse the same clip with explicitly canned verdict combinations.

| Metric | Observed |
| --- | ---: |
| Cases passed | 20 / 20 |
| Expected alert events matched | 17 |
| False alerts | 0 |
| Missed events | 0 |
| Duplicate alerts | 0 |
| Case execution errors | 0 |
| Mean source-time delay after expected threshold | 0.024 s |
| Mean engine alert latency | 0.090 s |

Engine alert latency is wall time from the first processed frame at the expected
threshold to new-alert emission. It does not measure capture-to-browser time.
The source delay includes the deliberately hidden threshold observation that
waits until 5.4 s to produce an alert. Wall timings vary by machine and load.

## Continuous two-camera backend run

A real-time synthetic source fed the application for **300.095 seconds without
restart**. This used the real FastAPI handlers through TestClient, WebSocket
updates, camera workers, shared verifier scheduling, evidence writer and SQLite.
The default verifier explicitly returned unclear; no Gemini request was made.

| Metric | Observed |
| --- | ---: |
| WebSocket messages received | 3,595 |
| Distinct incidents/alerts | 45 |
| Decisions saved through HTTP | 45 |
| Alerts with ready evidence | 45 |
| Duplicate incident IDs | 0 |
| Thread count after startup | 10 throughout sampled checks |
| Process peak RSS on macOS | approximately 148 MiB |

The thread count began at seven before lazy background workers started. Peak RSS
is a process high-water mark, not a memory-leak diagnosis. Both cameras stayed
active, periodic health/status requests succeeded, and stopping completed safely.

## Reproduce

Install `backend/app/requirements-dev.txt` in the environment. From the repo root:

```sh
python -B eval/generate_fixtures.py
python -B eval/run_eval.py --output eval/generated/evaluation-report.json
python -B -m unittest discover -s eval/tests -v
python -B eval/soak_backend.py --output eval/generated/soak-report.json
```

From `backend/`:

```sh
python -B -m unittest discover -v
```

The soak driver creates a fresh generated data directory per run. Its default
duration is five minutes; `--seconds 20` is a shorter wiring check and must not
be reported as a five-minute result. Durations are multiples of 20 seconds.

## Still requires real integration

- Real detector/camera FPS, tracking stability and source reconnection behavior.
- Person 2's real compiler/verifier, credentials, accuracy and provider latency.
- Person 3's complete browser workflow and real capture-to-UI alert latency.
- A representative real-footage CSV evaluation set and final submission video.

The integrated evaluator exists, but no real detection/classification accuracy
is claimed. No teammate-owned modules or shared contract fields were changed.
