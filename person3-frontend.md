# Person 3: Frontend engineer — starter prompt

Paste everything below this line as the first message of a Claude Code session started at the repo root.

---

Read CLAUDE.md first. I am Person 3, the frontend engineer, and I own frontend/. Do not edit
other folders. The backend is not ready yet, so build against a mock server first.

Stack: Vite + React + TypeScript + Tailwind. One page with four steps in a top nav:
1 Setup, 2 Review, 3 Monitor, 4 Alerts. During monitoring, alerts also show in a side drawer.
src/types.ts mirrors backend/app/models.py exactly. All calls live in src/api.ts.

0. Mock server: a small Node server (Express + ws) on port 8000, started with `npm run mock`,
   implementing every route in contracts/api.md with canned data from contracts/*.json.
   Mock two cameras (cam_entrance, cam_exit); their snapshots and streams serve sample frames.
   /ws sends state messages with exit progress ticking 0 -> 5 s, then an urgent alert at 5.4 s.
   Vite proxies /api, /ws and /evidence to :8000, so switching to the real backend needs no
   code changes.
1. Setup: a textarea prefilled with the demo policy. A camera list where you add cameras
   (name + source such as webcam:0 or a phone stream URL) via PUT /api/cameras. For the
   selected camera, its snapshot with a canvas overlay for zones: click to add polygon points,
   click the first point to close, or drag for a rectangle. Name, edit and delete zones. Save as
   normalized coords with PUT /api/zones. "Compile policy" calls POST /api/policy/compile with a
   loading state.
2. Review: one card per rule showing name, zone, the condition in plain English ("Bag is
   probably opaque"), a severity badge, an editable duration and severity, and an enable
   toggle. Warnings appear as amber notes. Unsupported items appear as gray "Can't monitor this"
   cards with the explanation. "Start monitoring" calls PUT /api/policy, then
   POST /api/monitor/start.
3. Monitor: a camera grid, one tile per camera (<img src="/api/stream/{camera_id}">) with its
   name and a live/offline dot; click a tile to enlarge it. Video stays dominant and
   uncluttered. Rule status chips from /ws, such as "Exit obstruction: 3.2 / 5 s" with a thin
   progress bar that turns red at the threshold. Each chip sits on its own camera's tile. FPS
   per camera and a connection indicator.
4. Alerts: newest first, open urgent alerts pinned on top. Each card shows the evidence clip
   (<video autoplay muted loop>) or frame with its bbox drawn on an overlay, title, observation,
   rule name, camera name, confidence %, and relative time. Filter by camera. Confirm / Dismiss /
   Unclear buttons call POST /api/alerts/{id}/decision and the card shows the result.
   Filter: Open / Reviewed. A new alert shows a toast and a badge count on the nav.

Design: a calm, dark control-room look. Urgent is red, review is amber. Large click targets.
It must read well on a projector at 1920x1080 and on a 1366x768 laptop. No internal model
details on the live view. The WebSocket reconnects automatically.

Start by proposing a short plan, then build types.ts and the mock server.
