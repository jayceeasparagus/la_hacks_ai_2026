# Synthetic temporal replay results

Checkpoint: approved contracts and persistent-object engine. Evaluated on
2026-10-17 using Python 3.12.14 and Pydantic 2.14.0. All 36 automated tests pass.
The project target is Python 3.11+; this run did not separately test Python 3.11.

Each input was written to JSONL, loaded back through Pydantic validation, and
replayed using source timestamps. All scenarios sample at 10 Hz.

| Scenario | Expected alerts | Actual alerts | Actual source timestamps (s) | Result |
| --- | ---: | ---: | --- | --- |
| exit_bag | 1 | 1 | [5.0] | PASS |
| walkthrough | 0 | 0 | [] | PASS |
| short_bag | 0 | 0 | [] | PASS |
| two_bags | 2 | 2 | [5.0, 5.0] | PASS |
| dropout | 1 | 1 | [5.0] | PASS |
| id_switch | 1 | 1 | [5.0] | PASS |
| reentry | 2 | 2 | [5.0, 16.0] | PASS |
| long_dropout | 1 | 1 | [9.3] | PASS |
| threshold_dropout | 1 | 1 | [5.4] | PASS |
| empty | 0 | 0 | [] | PASS |
| chair | 1 | 1 | [5.0] | PASS |
| outside_reset | 1 | 1 | [9.5] | PASS |

The two-camera isolation tests also pass for independent worker threads and
interleaved source frames with identical tracking IDs.

These are synthetic engine checks, not detection-accuracy or production-safety
measurements. No detector, camera, Gemini call, evidence encoder, database or
HTTP server participated. Real-video false positives, misses, duplicate rates
and wall-clock alert latency remain unmeasured. The threshold-dropout case
deliberately waits until 5.4 s for a visible detection, 0.4 s after its 5 s threshold.

Reproduce from backend/:

```sh
python -B -m unittest discover -v
python -B -m engine.fake_tracks ../eval/generated
python -B -m engine.replay ../eval/generated/exit_bag.tracks.jsonl
```
