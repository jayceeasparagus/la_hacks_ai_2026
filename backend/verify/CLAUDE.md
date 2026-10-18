# backend/verify: crop verifier (Person 2)

`verify_crop(crop, check) -> Verdict` in `verifier.py`. Person 4's engine calls it from a thread pool.
`crop` is an OpenCV BGR uint8 array. `check` is `transparent_bag`, `professional_camera` or
`person_down` (stretch). Pick it with `verify.prompts.CHECK_FOR_ATTRIBUTE[rule.attribute.name]`.
`answer=True` means "yes" to the question (the bag is transparent, the camera is professional,
the person is down). `None` means unclear, which leads to a manual-review alert.

## Guarantees
- Never raises and never retries. The total budget is about 4 s, including up to 1 s waiting for the
  rate limiter.
- Fixed reasons when there's no model answer: "object too small to judge" (a side under 40 px),
  "verification busy" (limiter full), "verification timed out", "verification unavailable" (an error,
  bad JSON, or Gemini paused by the breaker in `policy/llm.py`).
- Answers below `CONFIDENCE_THRESHOLD` (0.55) become unclear. Tune this with `verify.eval`.
- LRU cache (256 entries) keyed by (check, sha1 of the JPEG). Crops are sent as JPEG, longer side at
  most 512 px.
- `ratelimit.LIMITER` is shared by every camera thread: 2 requests/s, at most 4 in flight. A slot is
  freed when the request really finishes, even if we stopped waiting for it.
- `POLICYLENS_FAKE_LLM=1` gives deterministic verdicts for engine tests:
  - bright crops (mean >= 128) are clear bags
  - dark crops (mean < 100) are professional cameras
  - crops more than 1.2x wider than tall are people down

## Tools (run from backend/)
- `python -m verify.cli <folder> [--check X]`: a verdict and latency per image.
- `python -m verify.eval data/verify`: accuracy, a confusion matrix with an unclear column, p50/p95
  latency, misclassified files and a threshold sweep. Layout: `data/verify/<check>/<yes|no>/*.jpg`.
- `python -m verify.crops boxes.csv --out data/verify`: cuts padded crops from clips. The CSV columns
  are `clip,time_s,x1,y1,x2,y2,check,label`.

Not done yet: there's no `clips/` folder and no API key, so no labeled set and no accuracy or latency
numbers exist.
