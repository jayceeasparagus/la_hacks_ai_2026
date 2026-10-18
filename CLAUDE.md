# PolicyLens: project context for Claude Code

## The problem
Cameras are everywhere, but nobody can watch every feed. Staff at a venue entrance or event
floor are juggling crowds, so the moments that matter (a blocked fire exit, a banned bag, an
unapproved pro camera, someone collapsing) get missed even when they are on camera.

## What we are building
PolicyLens turns any ordinary camera into a policy-aware attendant you program with a sentence.
An organizer types the venue's own rules in plain English. Gemini compiles them into structured
rules from a small, fixed grammar. Each camera feed (two or three at once) runs through a local
detector, tracker and zone/timer engine. Gemini verifies only uncertain crops. Evidence-backed alerts go to a human
review queue. The camera stops just recording and starts understanding; the system never
enforces anything, and operators decide.

Who it is for: anyone running a physical space with rules, from a campus event or corner store
up to stadium gates, malls and hospital lobbies.

Pitch: other AI cameras watch for what the model thinks is dangerous. PolicyLens watches for
what you said matters. Natural language becomes an executable, transparent policy for a
physical space.

This is a 24-hour hackathon project (LA Hacks).

## Inspiration and positioning
Inspired by HawkWatch (TreeHacks 2025 grand prize), which turns any camera into an AI security
system by sending video to Gemini and auto-alerting security. We share its framing (passive
cameras become active, evidence-backed alerts; safety as well as security). We differ on purpose:
1. User-defined policies instead of a fixed threat list.
2. Local detection + tracking on every frame; Gemini only on the policy and selected crops.
3. Temporal rules ("for more than 5 seconds") with one alert per incident.
4. A human confirms every alert; nothing is sent to authorities automatically.
All code is written from scratch. The README credits HawkWatch as inspiration.

## The demo (everything serves this)
Prompt: "At the main entrance, only clear bags are permitted and professional cameras require
review. Keep the emergency exit clear; alert if a bag or chair blocks it for more than five seconds."

Cameras: cam_entrance (laptop webcam) covers the main_entrance zone; cam_exit (phone or USB
webcam) covers the emergency_exit zone. One sentence programs both cameras.

Compiled rules:
1. clear_bag    object_attribute   zone main_entrance   backpack/handbag/suitcase, transparent expected=true -> review
2. pro_camera   object_attribute   zone main_entrance   camera, professional expected=false             -> review
3. blocked_exit persistent_object  zone emergency_exit  backpack/handbag/suitcase/chair for >= 5 s     -> urgent
A violation is when the observed attribute != expected.
Rule 3 is the technical centerpiece: zones + tracking + duration + ignoring brief passes + one
alert per incident.

## Definition of done
- A user enters the demo policy without editing code; it becomes visible, editable rule cards.
- The user can draw and name at least two zones on the camera frame.
- A clear bag does not alert. An opaque bag produces an evidence-backed review alert.
- Exit obstruction alerts only after the configured duration, and only once per incident.
- An operator can confirm, dismiss or mark unclear.
- Unsupported policies (for example concealed weapons) produce an honest warning.
- The system runs a five-minute continuous demo without restarting.
- Two live cameras run at once under one policy, each with its own zones, and every alert
  names the camera it came from. If one camera drops, the other keeps working.

## Stretch goals (only after the definition of done passes)
1. Person down: "Alert if someone is on the floor for more than 10 seconds." A persistent rule
   on person tracks whose box is wider than tall, verified by Gemini on the crop, severity
   urgent, worded "Possible person down". Needs a contract change (attribute lying_down for
   person), made by Person 4.
2. Incident timeline on each alert: entered zone, threshold reached, verified, operator decision.

## Architecture
Prompt -> Gemini compiler -> Pydantic validation + capability check -> rules (user confirms)
Per camera (webcam, phone stream or clip) -> OpenCV capture -> YOLO-World detection -> ByteTrack -> RuleEngine
(zones, timers, dedup) -> async Gemini crop verification for selected crops only -> alerts in
SQLite -> FastAPI (REST + MJPEG stream + WebSocket) -> React UI (setup, review, monitor, alerts).

## Stack
- Python 3.11, FastAPI, uvicorn, Pydantic v2, opencv-python, ultralytics (YOLO-World
  yolov8s-worldv2.pt with set_classes, built-in ByteTrack via model.track), google-genai, sqlite3.
- Frontend: Vite, React, TypeScript, Tailwind. Dev server proxies /api, /ws, /evidence to :8000.
- Secrets in .env: GEMINI_API_KEY, GEMINI_MODEL. Never commit .env.

## Contracts: do not change without asking
backend/app/models.py and contracts/ define Zone, Rule, CompileResult, TrackFrame, Alert,
RuleState, Verdict, the REST API and WebSocket messages. They are the source of truth. If a task
seems to need a contract change, stop and tell the human exactly what and why. Never rename fields.

## Ownership
- Person 1, vision:    backend/vision/
- Person 2, policy/AI: backend/policy/, backend/verify/
- Person 3, frontend:  frontend/
- Person 4, integration: backend/app/, backend/engine/, backend/store/, eval/, README.md
Work only in your owner's folders unless the human asks otherwise.

## Engineering rules
- Never act on unvalidated LLM output. Every Gemini response parses into a Pydantic model;
  on failure retry once, then use the fallback.
- Never send every frame to Gemini. Only crops the engine selects, cached per track_id,
  rate-limited. Gemini calls never block the frame loop (thread pool).
- Alert wording is hedged: "possible", "probably". Uncertain results become "manual review".
- One alert per incident (rule_id + track_id). Brief passes through a zone never alert.
- Every module runs on a recorded clip from clips/ through a CLI or test, deterministically.
  After a change, run it, and report what you ran and what you saw.
- Simple, readable code beats abstraction. No auth, no Docker, no microservices.
- Log FPS per camera, end-to-end alert latency and Gemini latency.
- Multiple cameras: everything is keyed by camera_id. Each camera gets its own capture, YOLO
  model instance, tracker and RuleEngine in its own thread (ultralytics track(persist=True)
  keeps tracker state on the model, so a shared model would mix track ids across cameras).
  Gemini calls share one global rate limit. A dropped camera shows as offline and reconnects
  without affecting the others. Cap at 3 cameras; lower resolution (960 px wide) before FPS.

## Never build
Face recognition, person identification, demographic inference, concealed-weapon detection,
following people or objects across cameras (re-identification), automatic enforcement or
auto-calling authorities, custom model training,
mobile apps, SMS or dispatch integrations, real authentication.

## Run
- Backend:  cd backend && uvicorn app.main:app --port 8000
- Frontend: cd frontend && npm run dev
- Replay:   cd backend && python -m engine.replay ../clips/exit_bag.tracks.jsonl
