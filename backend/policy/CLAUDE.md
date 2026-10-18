# backend/policy: policy compiler (Person 2)

`compile_policy(prompt, zones) -> CompileResult` in `compiler.py`. It never raises: bad input becomes
warnings or `unsupported` entries. `compile_policy_with_info()` also returns which path answered
(`gemini`, `cache`, `fallback` or `fake`) and the latency.

## Pipeline
normalize the prompt (2,000 char cap) -> cache -> Gemini (`llm.py`, schema from `draft.py`, prompt from
`prompts.py`, 1 retry, 30 s total, `POLICYLENS_COMPILE_TIMEOUT_S`) -> `capability.finalize()` -> cache.
On any failure: `fallback.py` (keyword matching for the demo prompt and paraphrases) -> `capability.finalize()`. Gemini answers and
fallback answers both pass through `capability.py`, which is the real safety net.

## Contracts
`contracts.py` imports from `app.models` when that module exists. Until then it uses a TEMPORARY
mirror of the approved models on `origin/person4-integration`. Delete the mirror after the merge.
Never change the contracts from here. The approved contract differs from the original briefing:
- `SUPPORTED_ATTRIBUTES` maps object -> attributes (`{"backpack": ("transparent",)}`). Use
  `synonyms.objects_with_attribute()` and `synonyms.attribute_names()`, never index it by attribute.
- Severity is only `review` or `urgent` (no `info`).
- `Rule` validates itself: ids and names can't be empty, persistent rules allow only bags and chairs
  with no attribute, and attribute rules need every object to support the attribute. Zones need at
  least 3 polygon points, and every model rejects unknown fields.
- To check compatibility, put their `app/models.py` on `PYTHONPATH` and run the tests. On
  2026-10-17 all tests passed, and the demo compile matched `contracts/examples.json` exactly.

## Gemini SDK (google-genai 2.31.0, Interactions API; checked against the installed source)
- `client.interactions.create(model=..., input=str | [parts], system_instruction=str,
  response_format={"type": "text", "mime_type": "application/json", "schema": {...}},
  generation_config={"thinking_level": "minimal"}, timeout=<seconds>)` -> `.output_text`.
- Image part: `{"type": "image", "data": <base64>, "mime_type": "image/jpeg"}`, after the text part.
- The client retries 4 times by default. We pass `HttpRetryOptions(attempts=0)`; `attempts=1` would
  still retry once, because the Interactions client maps attempts straight to max_retries. We also
  enforce our own wall-clock timeout with `future.result(timeout=...)`.
- Schemas go through `draft.structured_output_schema()`, which inlines `$ref`s and drops titles and defaults.
- **Vertex AI does not serve the Interactions API**: in Vertex mode the SDK posts to
  `/v1beta1/interactions` and Google returns 404 (checked 2026-10-17). So with
  `GOOGLE_GENAI_USE_VERTEXAI=true`, `llm.py` uses `models.generate_content` with `response_json_schema`,
  `system_instruction`, image `Part.from_bytes` and `thinking_budget=0` for the verifier. The default
  model there is `gemini-2.5-flash`, because Vertex has no `-latest` aliases. Express-mode keys
  (`GOOGLE_API_KEY`) build `genai.Client(vertexai=True, api_key=...)`. With a fake key the Vertex
  path reaches auth (401), so the route is right. Run `python -m policy.check_gemini` to test a real setup.
- Checked live on 2026-10-18 with a Vertex express key: the schemas are accepted and `pytest -m live` passes.
- Express keys go to the regional `us-central1` endpoint by default (`POLICYLENS_VERTEX_LOCATION`, `global`
  restores the SDK default). Why: the global endpoint took ~11 s on a new or idle connection; us-central1
  answered a cold compile in 3.6 s and a warm image check in 1.25 s. A bad location fails fast and the
  compiler falls back offline.

## Environment
`GEMINI_API_KEY`, `GEMINI_MODEL` (default `gemini-flash-latest`), `GEMINI_VERIFY_MODEL`,
`POLICYLENS_FAKE_LLM=1` (offline: fallback compiler and fake verdicts), `POLICYLENS_CACHE_DIR`.
The CLIs load `.env` with python-dotenv. The FastAPI app must call `load_dotenv()` itself.
Dependencies: google-genai, pydantic, python-dotenv, opencv-python, numpy, pytest.

## Run (from backend/)
- `python -m policy.cli "<policy>" [--zones policy/tests/fixtures/zones_demo.json] [--json] [-v]`
- `python -m pytest policy/tests verify/tests` runs offline. `-m live` runs the Gemini tests.

## Decisions and gotchas
- Whole-frame cameras (`capability.whole_frame_cameras`): when every camera has exactly one zone covering
  at least 90% of its frame (the site safety demo), every rule is copied to every camera's zone, whatever
  place the text names, and Gemini is shown a single "Everywhere" zone. Drawn zones keep normal scoping, so
  a place that isn't drawn still asks "Which zone…?" (test 06).
  Why: the live demo has no zones by design; without this, a policy naming no zone compiled to 0 rules.
- The demo prompt must compile with zero warnings. Don't add warnings for things the text states clearly.
- Persistent rules never include `person`. The one exception is the person-down rule (`lying_down`).
- When the fallback finds no duration it leaves it null, so capability's default (10 s, with a warning)
  applies. Briefing 7.7 said to default to 5, but test 5 expects 10 for "Keep the exit clear".
- Prohibitions ("No bags", "Chairs are not allowed", "Backpacks are banned"; `synonyms.is_prohibition`, no
  time stated, no leave/unattended/block/clear words) mean any such object in view: a persistent rule with
  1 s, severity from the text (review, urgent at exits), no time warning, even if the model invented a time.
  Ids are `no_bags` / `no_chairs` / `no_objects` ("No-bag policy"). The `no_` prefix is a convention that
  `engine/alerts.py` ("Possible backpack in view") and `Demo.tsx` ("Any bag in view") key on, because Rule
  has no field for it. "No cameras" stays the pro-camera check; "No people" and "No smoking" go to unsupported.
  Why: live Gemini compiled "No backpacks or bags." to a 10 s "unattended_bag" rule with a time warning.
- `llm.py` has a circuit breaker: after 3 failures in a row, Gemini is skipped for 30 s, so offline
  compiles go straight to the fallback and verifications return "verification unavailable".
  `llm.status()` reports the mode, the models, whether a key is set and whether Gemini is paused,
  for a health endpoint.
- Person down (stretch) is off until `"lying_down" in app.models.SUPPORTED_ATTRIBUTES["person"]`,
  `Attribute.name` accepts `"lying_down"`, and the Rule validator allows that attribute on a
  persistent person rule. The approved contract says person down stays unsupported for the MVP, so
  for now those requests go to `unsupported`.

## Construction-site safety gear (PPE)
- `hard_hat` and `safety_vest` are attributes on `person` (object_attribute rules, expected=true).
  "Safety gear" or "PPE" compiles to both rules. Gloves, goggles, boots, masks and harnesses go to
  `unsupported`.
- This needs a contract change in `app/models.py`: `SUPPORTED_ATTRIBUTES["person"]` must include both,
  and `Attribute.name` must accept them. The mirror in `contracts.py` already has the change. With the
  old contract, the PPE prompt section, schema options and tests switch off (`synonyms.ppe_supported()`).
- The verifier checks have the same names (`hard_hat`, `safety_vest`), and
  `verify.prompts.CHECK_FOR_ATTRIBUTE` maps each attribute to its check.
- In a sentence that already made a rule, the fallback reports only standalone unsupported topics
  (injection, concealed items, weapons, other PPE). "All employees must wear vests" is a rule, not an
  identity request.

## Open proposals for Person 4 (contract changes need their sign-off)
1. Add `description: str` to `Rule`, filled from `describe.describe_rule()` ("Bag is probably opaque").
2. Person down: add `lying_down` for `person`. The engine treats a `persistent_object` rule *with* an
   attribute as "verify the crop after the duration", using `verify.prompts.CHECK_FOR_ATTRIBUTE`.
