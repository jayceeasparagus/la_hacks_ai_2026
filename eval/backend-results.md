# Combined backend validation

The integration uses main's FastAPI server, settings, SQLite store, policy/compiler,
verifier, source adapters and safety-gear contracts. Person 4's bounded scheduler,
source-frame buffering, evidence safeguards, recorded evaluation and soak driver
are integrated with those interfaces. Duplicate application/configuration stacks
were removed; their original implementations remain in Git history.

## Automated checks

Run from `backend/`:

```sh
POLICYLENS_FAKE_LLM=1 python -B -m pytest app/tests engine/tests store/tests policy/tests verify/tests ../eval/tests -q
```

**265 tests passed, 17 live-provider tests skipped**, with 87 additional unittest subtests.
Validated with Python 3.12.14 on the local Mac.

Live-provider tests are skipped; no Gemini request or actual detector is used.
Regressions include idle verification delivery, disconnect invalidation with reused
track IDs, shared capacity across monitor restarts, bounded evidence encoding,
late evidence preserving decisions and other alert fields, and HTTP byte ranges.
Main's compiler, verifier, hard-hat/vest rules and existing server tests are included.

## Recorded-video evaluation

```sh
python -B eval/generate_fixtures.py
python -B eval/recorded_eval.py --output eval/generated/recorded-report.json
```

The separate `eval/recorded_cases.csv` contains 20 cases: generated, visibly
synthetic video plus saved tracks and explicitly canned attribute verdicts.
It passes 20/20 cases: 17 expected alerts matched, no false/missed/duplicate
alerts or execution errors. Mean source delay is approximately 0.024 seconds;
wall latency varies by load. Wall latency measures the first processed frame
at the expected threshold to alert emission, excluding HTTP/UI/evidence latency.
Main's `eval/run_eval.py` and `eval/cases.csv` retain their existing formats.

## Continuous backend check

```sh
python -B eval/soak_backend.py --output eval/generated/soak-report.json
```

This uses two synthetic sources at real speed, an explicit unclear stub verifier,
TestClient HTTP/WebSocket, the actual workers, SQLite and evidence writer. The
five-minute run expects 45 distinct incidents, each reviewed through HTTP and
with ready evidence. `--seconds 20` is only a short wiring check (3 incidents).
The earlier branch's five-minute measurements in prior revisions are historical;
merged-backend results are recorded below after validation.

## Remaining validation

Real camera/detector FPS and reconnection behavior, actual Gemini accuracy and
latency, the browser workflow, representative real-footage evaluation, and the
submission recording still require integrated hardware/provider/UI testing.
Synthetic results establish functional behavior, not real-world model accuracy.
Shared contracts and teammate-owned modules match main without local modifications.
