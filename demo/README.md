# Demo scenes

Each scene in `scenes/` is a JSON file with cameras, zones, rules and the plain-English policy
that compiles to exactly those rules. Load one, start the server, and press start in the UI or
call the API.

| Scene | Footage | What it shows | Needs |
| --- | --- | --- | --- |
| `lobby.json` | CAVIAR lobby, real video | 3 cameras: an urgent "Possible exit obstruction" alert at 42.8 s, "Possible unattended bag" alerts at 28.2 s and 30.1 s. People walking through never alert. | Nothing: runs today, no detector, no Gemini key |
| `venue.json` | Pexels | Clear tote passes; a shoulder-mounted video camera gets a review alert; phones don't count | Person 1's vision + Gemini key |
| `construction.json` | Pexels | Hard-hat and hi-vis-vest checks on each person's crop | Person 1's vision + Gemini key |
| `site_safety.json` | WILDTRACK plaza (camera 3), looping | The live policy demo (`/#/demo`): type a policy and it applies at once; "No backpacks or bags." flags every bag in view | Tracks in `clips/demo/` (see below); gear rules need Gemini |
| `tracking.json` | Pexels | A busy lobby: many anonymous person tracks, zero false bag alerts | Person 1's vision |

Before the scenes needing vision can run, Person 1's `person1/vision` must be merged and its
requirements installed. Until then their cameras show `offline` with that explanation. Without
`GEMINI_API_KEY`, attribute checks become honest "Manual review needed" alerts.

## Get the footage

The videos aren't in git. Download them from the links in `clips/SOURCES.md` into `clips/caviar/`
and `clips/pexels/` with the file names listed there. Then build the lobby tracks from CAVIAR's
hand-labelled ground truth, from `backend/`:

```sh
python -B ../eval/caviar_tracks.py ../clips/caviar/lb1gt.xml  --video ../clips/caviar/LeftBag.mpg          --camera-id cam_lobby_east    --out ../clips/caviar/LeftBag.gt.tracks.jsonl
python -B ../eval/caviar_tracks.py ../clips/caviar/lb2gt.xml  --video ../clips/caviar/LeftBag_AtChair.mpg  --camera-id cam_lobby_seating --out ../clips/caviar/LeftBag_AtChair.gt.tracks.jsonl
python -B ../eval/caviar_tracks.py ../clips/caviar/lbpugt.xml --video ../clips/caviar/LeftBag_PickedUp.mpg --camera-id cam_lobby_desk    --out ../clips/caviar/LeftBag_PickedUp.gt.tracks.jsonl
```

These tracks are ground truth, not detector output. They show how the rules, timers, evidence
and review flow behave on real footage. They're named `.gt.tracks.jsonl` because Person 1's
`python -m vision.dump <clip>` writes `<clip>.tracks.jsonl` next to the clip; a shared name
would overwrite the ground truth.

**Detector check (2026-10-17, CPU, 6.1 fps):** Person 1's YOLO-World tracked the 9 people in
`LeftBag.mpg` with no ID switches, but **did not detect the left bag**. It's about 16x21 px in this
384x288 overhead fisheye footage. So the lobby scene uses ground truth on purpose, and the
`lobby_exit_walkway_detector` eval row records that miss. For a live demo, film the bag at a
normal height and distance.

## Live policy demo (`site_safety.json`)

From `backend/`: `POLICYLENS_SCENE=../demo/scenes/site_safety.json uvicorn app.main:app --port 8000`, then
`cd frontend && npm run dev` and open `http://localhost:5173/#/demo`. The page starts monitoring by
itself. Type a policy, or click an example, and it compiles, saves and swaps the rules into the running
cameras (`PUT /api/policy` is allowed while monitoring); the videos keep playing.

- Cameras are `loop:<tracks.jsonl>@<video>` sources: Person 1's `vision.dump` tracks over the real clip,
  looped forever with the same track ids, at most 25 fps, skipping ahead if the machine falls behind.
  A looping camera alerts once per rule and track for each applied policy, not on every loop.
- Each camera has one whole-frame zone, so there are no zones to draw or name: every rule covers every
  camera, alerts don't mention a zone, and the stream draws no zone outline.
- The plaza clip is `clips/demo/wildtrack_cam3.mp4`: the WILDTRACK trim scaled to 1280x720 (the size the
  detector uses anyway; the 2.9K original was too heavy to decode live), with tracks from
  `python -m vision.dump` (about 25 min on CPU; ~19 people per frame, ~64 bags over 1 s).
- Gear checks on the plaza go to Gemini live, once per person: a looping camera remembers each track's
  answer, so later loops don't ask again. With ~285 people a gear policy still means hundreds of calls on
  the first loop (2 per second; the rest show "unclear"). Bag bans need no Gemini at all.
- Scenes can name `cached_verdicts` (`ppe_verdicts.json`, real Gemini answers keyed by clip, track
  id and check), used before any live call. If you change a clip or its tracks, check that every track that can
  reach the 1 s threshold is cached: the engine bridges detection gaps of up to 1 s, so a track with only
  9 frames spread over more than a second still gets verified (construction track 26 did). Missing ones
  go to live Gemini, or become "Manual review needed" offline.
- Labels on the stream are neutral: "Hard hat: yes" (green), "not seen" (amber), "unclear" or
  "checking" (gray).

### Add a video to `/#/demo`

1. Put the clip in `clips/pexels/` (add its link to `clips/SOURCES.md`) and dump its tracks, from
   `backend/` (needs Person 1's vision requirements and `backend/vision/weights/yolov8s-worldv2.pt`):

   ```sh
   python -m vision.dump ../clips/pexels/loading_dock_123.mp4
   # options: --imgsz 640 (default), --camera-id (unused by loop: sources, the scene's id wins)
   ```

   It writes `loading_dock_123.tracks.jsonl` and `loading_dock_123.annotated.mp4` next to the clip,
   and prints per-class detection counts, unique ids and the longest tracks.
2. Add a camera to `site_safety.json` with
   `"source": "loop:../../clips/pexels/loading_dock_123.tracks.jsonl@../../clips/pexels/loading_dock_123.mp4"`
   (paths are relative to the scene file), a whole-frame zone `[[0, 0], [1, 0], [1, 1], [0, 1]]`
   for it, and, for gear checks, a `cached_verdicts.cameras` entry (see the note above). At most 3 cameras.

Prohibition rules like "No backpacks or bags" alert only on what the dump detected: a `backpack`,
`handbag` or `suitcase` track lasting at least about 1 s. The current clips have none
(warehouse: three handbag flickers, longest 0.4 s; construction: one backpack, 0.25 s), so pick
footage where a bag is clearly visible for a few seconds. Check a dump from `backend/`:

```sh
python -c "import json,sys;s={};[s.setdefault((t['class_name'],t['track_id']),[f['ts']]).append(f['ts']) for f in map(json.loads,open(sys.argv[1])) for t in f['tracks'] if t['class_name']!='person'];[print(*k,f'{min(v):.1f}-{max(v):.1f} s') for k,v in s.items()]" ../clips/pexels/loading_dock_123.tracks.jsonl
```

## Run a scene

From `backend/`:

```sh
POLICYLENS_SCENE=../demo/scenes/lobby.json uvicorn app.main:app --port 8000
# optional: POLICYLENS_SOURCE_SPEED=4 plays replays 4x faster (handy for rehearsing)
```

Then:

```sh
curl -X POST localhost:8000/api/monitor/start
curl localhost:8000/api/alerts            # alerts with evidence image + clip URLs
```

Open `http://localhost:8000/api/stream/cam_lobby_east` for the live annotated stream. Evidence
files are served under `/evidence/`. Loading a scene replaces the saved cameras, zones and
rules. To show the compiler, `POST /api/policy/compile` with the scene's `policy` sentence:
it returns the scene's rules.

## Score it

```sh
python -B ../eval/run_eval.py ../eval/cases.csv      # includes the three lobby rows
python -m verify.ppe_crops ../datasets/ppe/construction_site_safety/css-data --out ../datasets/verify_crops --per-label 30
python -m verify.eval ../datasets/verify_crops       # needs GEMINI_API_KEY for real numbers
```

Current results:
- lobby rows: 3/3 alerts at the expected time, 0 false, 0 missed
- `verify.eval` on PPE crops: not measured yet (needs a Gemini key)
