# Next session: make the "prompt → policies → videos with detections" demo work

Paste everything below into a new Claude Code session started at the repo root
(`C:\Users\andzh\OneDrive\UCI\personal project\la hacks`).

---

Read `CLAUDE.md`, `backend/policy/CLAUDE.md`, `backend/verify/CLAUDE.md`, `contracts/api.md`
and `demo/README.md` first. I'm on the WatchDog/PolicyLens team (LA Hacks). Fix the live demo
flow on the website so it works end to end. Start by proposing a short plan and asking me any
decisions listed under "Decisions", then implement.

## The demo we want

1. The website shows **example videos on the side**: construction site and warehouse to start
   (more later), playing continuously as "cameras".
2. I type a policy in plain English, e.g. *"Workers at the construction site need to wear a vest
   and a helmet."*
3. It compiles into the right policies. For that sentence: **2 rules**, hard hat and hi-vis vest,
   covering the construction videos.
4. The policies are **applied to the videos immediately**: no extra setup, zone drawing or
   restart. The videos show detections live, a box per worker plus a gear verdict ("Hard hat:
   yes / not seen"), and missing-gear alerts appear in the alert feed with evidence.
5. Typing a different policy reconfigures the same videos without restarting the server.

## Current state (verified 2026-10-18; re-check before relying on it)

- **Branches:**
  - `main` = `8102018`.
  - **`frontend-contract` (`70f3676`) is NOT merged.** It makes the React app speak
    `contracts/api.md`; without it the setup page crashes against the real backend. Base your
    work on it: branch from it, or merge it first if I agree.
- **Environment (Windows):**
  - venv at the repo root `.venv` (Python 3.11) has ultralytics, torch CPU, lap, CLIP, fastapi,
    google-genai. `ffmpeg` is on PATH. The frontend uses `npm` in `frontend/`.
  - `.env` at the repo root has a **Vertex AI express key** (`GOOGLE_GENAI_USE_VERTEXAI=true`,
    `GOOGLE_API_KEY`, `GEMINI_MODEL=gemini-2.5-flash`). Never print it or commit it.
- **Vertex latency:** the global endpoint takes about 11 s per call on a new or idle connection
  and about 0.7 s when warm. The regional `us-central1` endpoint answered a raw request in
  0.75 s on a new connection; it's not wired in yet (`policy/llm.py`, express mode via
  `base_url`). Time limits are now 30 s for compile (`POLICYLENS_COMPILE_TIMEOUT_S`) and 20 s for
  verify (`POLICYLENS_VERIFY_TIMEOUT_S`). `python -m policy.check_gemini` checks the setup.
- **Assets** (`clips/` and `datasets/` are git-ignored; they exist on this machine):
  - `clips/pexels/construction_workers_5434220.mp4` and `warehouse_4281236.mp4`, plus
    `*.tracks.jsonl` from `python -m vision.dump` (Person 1's **draft** TrackFrame format).
  - `demo/ppe_verdicts.json`: real Gemini hard-hat and vest verdicts per `clip:track_id:check`
    for those two clips (track ids from those dumps).
  - `demo/scenes/construction.json` (uses `clip:` sources), plus `lobby.json`, `venue.json`,
    `tracking.json`.
  - `frontend/public/examples/*.mp4`: pre-rendered PPE example videos (static, already on the
    landing page).
- **Server:**
  - `cd backend && uvicorn app.main:app --port 8000`.
  - `POLICYLENS_SCENE=<scene.json>` loads cameras, zones and rules at startup.
  - Camera sources:
    - `synthetic:<scene>`
    - `replay:<tracks.jsonl>` and `replay:<tracks.jsonl>@<video>` (real video)
    - `clip:` / `webcam:` / `url:` (live YOLO via Person 1's `vision/`)
  - The MJPEG stream (`/api/stream/{id}`) is drawn server-side by `app/render.py`.

## Root causes found (with evidence)

1. **No zones match the prompt.**
   - The website's default cameras and zones are `main_entrance` and `emergency_exit`. Against
     them, the example sentence compiles to **0 rules**, plus the warning "Which zone should …
     apply to?".
   - Against the construction scene's zones (`construction_zone`, `warehouse_floor`) it gives
     exactly 2 rules (`hard_hat`, `safety_vest`), but only on `construction_zone`; "construction
     site" doesn't reach `warehouse_floor`.
   - The capability rule today: an unnamed zone with more than one zone gets dropped and warned.
2. **The videos can't be driven efficiently.**
   - `replay:<tracks>@<video>` would show real footage without running YOLO live, but:
     - `engine.replay.read_frames` only accepts approved TrackFrames, so the `vision.dump` draft
       format fails on line 1 (`frame_index` is an extra field).
     - `ReplaySource` uses `loop=False`, so a clip ends and the camera shows "replay ended".
   - `clip:` sources run YOLO live on CPU at about 2–6 fps per camera: laggy, and slow to start.
3. **There's no "apply immediately".**
   - `POST /api/policy/compile` never activates rules. The UI needs Save + Start, and
     configuration edits while monitoring return 409 by contract (stop → save → start).
   - The setup page expects cameras and zones to be configured by hand.
4. **Gear verdicts aren't shown on the video.** `app/render.py` draws boxes, zones and timers,
   not per-person hard-hat and vest results. Verification is also slow on the global Vertex
   endpoint, and non-deterministic for a demo.

## Decisions (ask me before implementing)

- **Zone scope when the prompt names no matching zone:** for the demo, apply the rule to every
  camera zone, with a visible note. Or apply it only to zones whose camera or zone name matches
  words like site, construction, warehouse or workers. Recommendation: match by name first, else
  all zones, with a note.
- **Demo verifier:** use cached verdicts from `demo/ppe_verdicts.json` first (deterministic,
  offline), falling back to live Gemini for unseen tracks. Or always call Gemini live.
- **Demo mode surface:** a dedicated `/#/demo` page in the frontend (video wall on the side,
  prompt box, rule cards, alert feed). Or reshape the existing Setup → Watch flow.
- **Contract changes** need my sign-off. For example, a new `POST /api/policy/apply` that
  compiles, saves and restarts monitoring in one call must be added to `contracts/api.md`.
- **Wiring the regional Vertex endpoint** needs one live check, a few requests on my credits.

## Suggested plan (adjust after reading the code)

1. Merge or branch from `frontend-contract`. Never `git checkout` another branch in this folder
   while a dev server runs; use a worktree. A branch without `frontend/` broke the running Vite
   server last time.
2. **Replay source:**
   - Accept Person 1's draft track format, converting through `app.adapter.ContractAdapter`.
   - Add looping for demo cameras. Keep track ids stable across loops, or map looped ids back to
     the base id, so cached verdicts still match.
   - Convert or point the demo scene at `replay:<clip>.tracks.jsonl@<clip>.mp4`.
3. **New demo scene `demo/scenes/site_safety.json`:**
   - construction-site and warehouse cameras as looping replays
   - full-frame zones with natural names ("Construction site", "Warehouse floor")
   - no rules at start
4. **Compiler scope:** implement the zone-scope decision in `policy/capability.py` and
   `policy/fallback.py` (plus the Gemini prompt in `policy/prompts.py`). Add tests: the example
   sentence must yield hard hat + vest for the intended cameras, with and without Gemini (FAKE
   mode).
5. **Apply flow:** one action that compiles, shows the rule cards, then saves the policy and
   (re)starts monitoring automatically, so the videos pick up new rules within a couple of
   seconds.
6. **Verdicts on video:** a demo verifier that looks up `demo/ppe_verdicts.json` by
   `(camera/clip, base track id, check)` before calling Gemini. Then draw per-person gear labels
   on the annotated stream in `app/render.py`: green when all gear is seen, amber when some is
   "not seen", gray when unclear. Neutral wording, never "violation".
7. **Frontend:** a demo page with the video wall (MJPEG streams), the prompt box and rule cards,
   and a live alerts feed with evidence.
8. **Verify for real:**
   - Run the backend with the scene and the frontend dev server.
   - In the browser, type the example sentence: 2 rule cards appear, boxes and gear labels show
     on both videos, and alerts arrive.
   - Then type a second policy and confirm it reconfigures.
   - Run every suite: `POLICYLENS_FAKE_LLM=1 python -B -m pytest app/tests engine/tests
     store/tests policy/tests verify/tests ../eval/tests -q` from `backend/`, and
     `npm run build` in `frontend/`.
9. Commit to a new branch and push. Ask me before merging to `main`.

## Acceptance criteria

- **Rules:** "Workers at the construction site need to wear a vest and a helmet" gives 2 rule
  cards (hard hat, hi-vis vest) that cover the construction-site video (and the warehouse, if
  that's the agreed scope). That holds with Gemini and in offline FAKE mode.
- **Video:** within about 2 s of applying, both videos show worker boxes. Gear labels appear as
  verdicts arrive: instantly from the cache, at most about 20 s live.
- **Alerts:** missing-gear alerts appear in the feed with evidence. Confirm and dismiss work.
- **Reconfigure:** a second, different policy applies without restarting the server, and the
  videos keep playing (looping).
- **Offline:** everything works with no network, from cached verdicts and the offline compiler
  fallback.
- **Tests:** all test suites and the frontend build pass. Report exactly what you ran and saw.
