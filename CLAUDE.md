PolicyLens: project context for Claude Code
What we are building
PolicyLens lets event organizers program a camera with a sentence. It is a 24-hour hackathon
project (LA Hacks). An organizer types a venue policy in plain English. Gemini compiles it into
structured rules from a small, fixed grammar. One camera feed runs through a local detector,
tracker and zone/timer engine. Gemini verifies only uncertain crops. Evidence-backed alerts go
to a human review queue. The system never enforces anything; operators decide.

Pitch: natural language becomes an executable, transparent policy for a physical space.

The demo (everything serves this)
Prompt: "At the main entrance, only clear bags are permitted and professional cameras require
review. Keep the emergency exit clear; alert if a bag or chair blocks it for more than five seconds."

Compiled rules:

clear_bag object_attribute zone main_entrance backpack/handbag/suitcase, transparent expected=true -> review
pro_camera object_attribute zone main_entrance camera, professional expected=false -> review
blocked_exit persistent_object zone emergency_exit backpack/handbag/suitcase/chair for >= 5 s -> urgent
A violation is when the observed attribute != expected.
Rule 3 is the technical centerpiece: zones + tracking + duration + ignoring brief passes + one
alert per incident.

Definition of done
A user enters the demo policy without editing code; it becomes visible, editable rule cards.
The user can draw and name at least two zones on the camera frame.
A clear bag does not alert. An opaque bag produces an evidence-backed review alert.
Exit obstruction alerts only after the configured duration, and only once per incident.
An operator can confirm, dismiss or mark unclear.
Unsupported policies (for example concealed weapons) produce an honest warning.
The system runs a five-minute continuous demo without restarting.
Architecture
Prompt -> Gemini compiler -> Pydantic validation + capability check -> rules (user confirms)
Webcam or clip -> OpenCV capture -> YOLO-World detection -> ByteTrack -> RuleEngine
(zones, timers, dedup) -> async Gemini crop verification for selected crops only -> alerts in
SQLite -> FastAPI (REST + MJPEG stream + WebSocket) -> React UI (setup, review, monitor, alerts).

Stack
Python 3.11, FastAPI, uvicorn, Pydantic v2, opencv-python, ultralytics (YOLO-World
yolov8s-worldv2.pt with set_classes, built-in ByteTrack via model.track), google-genai, sqlite3.

Frontend: Vite, React, TypeScript, Tailwind. Dev server proxies /api, /ws, /evidence to :8000.
Secrets in .env: GEMINI_API_KEY, GEMINI_MODEL. Never commit .env.
Contracts: do not change without asking
backend/app/models.py and contracts/ define Zone, Rule, CompileResult, TrackFrame, Alert,
RuleState, Verdict, the REST API and WebSocket messages. They are the source of truth. If a task
seems to need a contract change, stop and tell the human exactly what and why. Never rename fields.

Ownership
Person 1, vision: backend/vision/
Person 2, policy/AI: backend/policy/, backend/verify/
Person 3, frontend: frontend/
Person 4, integration: backend/app/, backend/engine/, backend/store/, eval/, README.md
Work only in your owner's folders unless the human asks otherwise.

Engineering rules
Never act on unvalidated LLM output. Every Gemini response parses into a Pydantic model;
on failure retry once, then use the fallback.

Never send every frame to Gemini. Only crops the engine selects, cached per track_id,
rate-limited. Gemini calls never block the frame loop (thread pool).

Alert wording is hedged: "possible", "probably". Uncertain results become "manual review".
One alert per incident (rule_id + track_id). Brief passes through a zone never alert.
Every module runs on a recorded clip from clips/ through a CLI or test, deterministically.
After a change, run it, and report what you ran and what you saw.

Simple, readable code beats abstraction. No auth, no Docker, no microservices.
Log FPS, end-to-end alert latency and Gemini latency.
Never build
Face recognition, person identification, demographic inference, concealed-weapon detection,
multiple cameras, automatic enforcement, custom model training, mobile apps, SMS or dispatch
integrations, real authentication.

Run
Backend: cd backend && uvicorn app.main:app --port 8000
Frontend: cd frontend && npm run dev
Replay: cd backend && python -m engine.replay ../clips/exit_bag.tracks.jsonl
