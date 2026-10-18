# Person 4: Integration lead — starter prompt

Paste everything below this line as the first message of a Claude Code session started at the repo root.
Person 4 also owns the README, the eval numbers, the demo video, the pitch, and the checkpoint schedule.

---

Read CLAUDE.md first. I am Person 4, the integration lead, and I own backend/app/,
backend/engine/, backend/store/, eval/ and README.md. Contract changes need my sign-off.

PART A: rule engine, built first against replayed tracks (no camera or model needed).
- engine/fake_tracks.py generates synthetic TrackFrame JSONL scenarios: a bag left in the exit
  zone for 8 s, a person walking through in 2 s, a bag in the zone for 3 s then removed, two
  bags left at once, a bag whose detection drops out for 0.6 s mid-incident.
- zones.py: point-in-polygon on the bbox bottom-center (normalized coords).
- engine.py, RuleEngine.update(frame, tf) -> (rule_states, new_alerts):
  - persistent_object: a timer per (rule, track_id) while the object is in the zone. A 1.0 s
    grace period covers missed detections before a reset. Alert once when elapsed >= duration.
    The incident closes after the object is out of the zone for 2 s; a new entry is a new
    incident. People are ignored for this rule. If a track is lost and a same-class track
    appears in the same zone with high bbox overlap within 1 s, it inherits the timer.
  - object_attribute: once an object of the rule's classes has been in the zone for
    duration_seconds, pick its best crop (large, high confidence) and submit verify_crop in a
    ThreadPoolExecutor, once per track, at most 2 calls/s. Violation is
    verdict.answer != attribute.expected -> alert with the verdict's confidence. answer=None ->
    a "manual review" alert saying we couldn't tell. Compliant -> nothing.
  - Until Person 2's verifier lands, use a stub verifier with canned answers.
- alerts.py: hedged wording ("Possible exit obstruction", "A backpack remained inside the
  emergency-exit zone for 5.4 seconds."). Persistent-object confidence = mean detection
  confidence over the incident. Save an evidence JPEG with the bbox drawn and an MP4 of
  about the last 4 s from the ring buffer, written in a background thread.
- replay.py: `python -m engine.replay <tracks.jsonl>` prints alerts with timestamps.
- Tests for every synthetic scenario: exactly 1 alert for the 8 s bag, 0 for the walk-through,
  0 for the 3 s bag, 2 for two bags, 1 (not 2) for the dropout case, and two engines
  replaying two cameras' files at once produce independent alerts tagged with the right camera_id.

PART B: FastAPI app (app/main.py).
- One run-loop thread per camera: VisionPipeline -> RuleEngine -> store -> broadcast
  annotated frame + WebSocket messages. Until Person 1's pipeline lands, use a FakePipeline
  that plays a clip with OpenCV alongside its tracks JSONL.
- Every route and WebSocket message in the contracts. Serve /evidence. store/db.py: SQLite
  tables for alerts and decisions. Zones and policy saved as JSON files.
- Start and stop are safe to call repeatedly. Each loop reconnects if its camera drops, and one
  camera failing never stops the others. All loops share one Gemini rate limiter. Nothing
  in the loop may raise and kill it; log and continue.

PART C: eval (eval/).
- cases.csv: clip, rule, expected alert count, expected time window.
- run_eval.py runs the full pipeline on each clip at max speed and prints: correct detections,
  false alerts, missed events, duplicate alerts, mean alert latency.
- README.md: what it is, architecture diagram, how to run, eval results table, limitations.

Start by proposing a short plan, then Part A with the synthetic scenarios.
