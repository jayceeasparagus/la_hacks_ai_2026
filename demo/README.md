# Demo scenes

Each scene in `scenes/` is a JSON file with cameras, zones, rules and the plain-English policy
that compiles to exactly those rules. Load one, start the server, and press start in the UI or
call the API.

| Scene | Footage | What it shows | Needs |
| --- | --- | --- | --- |
| `lobby.json` | CAVIAR lobby, real video | 3 cameras: an urgent "Possible exit obstruction" alert at 42.8 s, "Possible unattended bag" alerts at 28.2 s and 30.1 s. People walking through never alert. | Nothing: runs today, no detector, no Gemini key |
| `venue.json` | Pexels | Clear tote passes; a shoulder-mounted video camera gets a review alert; phones don't count | Person 1's vision + Gemini key |
| `construction.json` | Pexels | Hard-hat and hi-vis-vest checks on each person's crop | Person 1's vision + Gemini key |
| `tracking.json` | Pexels | A busy lobby: many anonymous person tracks, zero false bag alerts | Person 1's vision |

Before the scenes needing vision can run, Person 1's `person1/vision` must be merged and its
requirements installed. Until then their cameras show `offline` with that explanation. Without
`GEMINI_API_KEY`, attribute checks become honest "Manual review needed" alerts.

## Get the footage

The videos aren't in git. Download them from the links in `clips/SOURCES.md` into `clips/caviar/`
and `clips/pexels/` with the file names listed there. Then build the lobby tracks from CAVIAR's
hand-labelled ground truth, from `backend/`:

```sh
python -B ../eval/caviar_tracks.py ../clips/caviar/lb1gt.xml  --video ../clips/caviar/LeftBag.mpg          --camera-id cam_lobby_east    --out ../clips/caviar/LeftBag.tracks.jsonl
python -B ../eval/caviar_tracks.py ../clips/caviar/lb2gt.xml  --video ../clips/caviar/LeftBag_AtChair.mpg  --camera-id cam_lobby_seating --out ../clips/caviar/LeftBag_AtChair.tracks.jsonl
python -B ../eval/caviar_tracks.py ../clips/caviar/lbpugt.xml --video ../clips/caviar/LeftBag_PickedUp.mpg --camera-id cam_lobby_desk    --out ../clips/caviar/LeftBag_PickedUp.tracks.jsonl
```

These tracks are ground truth, not detector output. They show how the rules, timers, evidence
and review flow behave on real footage. Detector accuracy on the same clips comes once Person 1's
pipeline runs on them.

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
