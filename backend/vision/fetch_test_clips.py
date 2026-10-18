"""Get the Pexels test clips used by vision tests (test_zones.json, evidence_run, dump).

Pexels' terms forbid automated downloading (Section 8: no programs or robots for automatic data
collection, no systematic copying) and redistributing the videos on their own (Section 5), so the
clips are not in git and this helper never downloads anything. You download each clip by hand;
it does the bookkeeping:

    python -m vision.fetch_test_clips                     # which clips are present / missing
    python -m vision.fetch_test_clips --open              # open the missing clips' Pexels pages
    python -m vision.fetch_test_clips --import ~/Downloads   # move downloaded files into clips/pexels/

On each page click "Free download" and pick the 1080p (Full HD) size. --import recognises a file
when its name contains the clip's Pexels id (Pexels' own file names usually do); anything it can't
match, rename by hand to the name in the list below.
"""

import argparse
import shutil
import webbrowser
from pathlib import Path

CLIPS_DIR = Path(__file__).resolve().parents[2] / "clips" / "pexels"

# local name -> (Pexels video id, page slug, what it tests)
CLIPS = {
    "gate_man_ticket": (7251544, "man-passing-a-ticket-gate", "single-lane turnstile: the ideal choke point"),
    "gate_pass_cards": (7952194, "people-swiping-their-pass-cards-before-entering", "queue at turnstiles, shoulder bag"),
    "gate_woman_metro": (11565901, "woman-walking-through-gate-at-metro-station", "handheld; whole-frame zone"),
    "gate_subway_turnstile": (39617498, "modern-subway-turnstile-entry-scene", "wider turnstile row, backpacks"),
    "gate_nyc_turnstile": (16967317, "the-everyday-act-of-walking-through-a-subway-turnstyle-in-new-york-city-the-video-is-silent-allowing-the-viewer-to-focus-on-the-visuals-of-the-scene-the-turnstyle-is-a-metal-structure-w", "handheld walk through gates"),
    "ppe_workers_walking": (5434223, "workers-walking-in-construction-site", "helmets and vests from behind"),
    "ppe_group_walking": (8965526, "construction-workers-walking-at-the-construction-site", "helmets and vests walking toward the camera"),
    "ppe_worker_entering": (5434217, "a-construction-worker-entering-a-building-basement", "one worker at an entrance"),
    "stadium_entrance_gameday": (39239779, "energetic-crowd-at-stadium-entrance-on-game-day", "dense crowd (person threshold)"),
    "stadium_fans_rabat": (34686011, "fans-walk-to-modern-stadium-in-rabat-morocco", "crowd walking to a stadium, backpacks"),
    "wembley_station_entrance": (3405719, "wembley-park-station-entrance", "far, night-time plaza"),
    "hotel_luggage_enter": (39596352, "travelers-with-luggage-enter-a-modern-hotel", "suitcases; carried-object timer pause"),
    "airport_couple_enter": (7423654, "couple-entering-a-airport", "two people entering; held-object exit check"),
    "airport_checkpoint_walkthrough": (27778672, "a-security-checkpoint-at-an-airport-with-people-walking-through", "busy checkpoint"),
    "airport_checkpoint_busy": (32654547, "busy-airport-terminal-security-checkpoint-scene", "corridor choke point, handbags"),
    "concert_fans_phones": (12719510, "fans-recording-concert-with-smartphones", "phones in a dark crowd"),
    "concert_man_filming": (12695730, "man-filming-concert", "one phone held up (not a pro camera)"),
    "street_smartphones": (39102147, "busy-street-life-with-people-using-smartphones", "phones in daylight"),
    "walking_phone_sidewalk": (7867420, "man-holding-a-cellphone-while-walking-on-the-sidewalk", "phone and bag in hand"),
}


def page_url(name: str) -> str:
    vid, slug, _ = CLIPS[name]
    return f"https://www.pexels.com/video/{slug}-{vid}/"


def present(name: str) -> bool:
    return (CLIPS_DIR / f"{name}.mp4").exists()


def status() -> list[str]:
    missing = [n for n in CLIPS if not present(n)]
    print(f"{len(CLIPS) - len(missing)} of {len(CLIPS)} Pexels test clips in {CLIPS_DIR}")
    for name, (vid, _, what) in CLIPS.items():
        mark = "ok     " if present(name) else "MISSING"
        print(f"  {mark} {name + '.mp4':38s} Pexels {vid:<9d} {what}")
    if missing:
        print("\nDownload each by hand (Free download -> 1080p), then run with --import <downloads folder>.")
        print("Or run with --open to open the missing pages.")
    return missing


def open_pages(names: list[str]) -> None:
    for name in names:
        print(f"opening {name}: {page_url(name)}")
        webbrowser.open(page_url(name))


def import_from(folder: Path) -> None:
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    files = [p for p in folder.expanduser().iterdir() if p.is_file() and p.suffix.lower() == ".mp4"]
    moved = 0
    for name, (vid, _, _) in CLIPS.items():
        if present(name):
            continue
        matches = [p for p in files if str(vid) in p.name]
        if len(matches) == 1:
            shutil.move(str(matches[0]), CLIPS_DIR / f"{name}.mp4")
            print(f"  moved {matches[0].name} -> {name}.mp4")
            moved += 1
        elif len(matches) > 1:
            print(f"  {name}: several files contain id {vid} ({', '.join(m.name for m in matches)}); rename one by hand")
    print(f"moved {moved} file(s)\n")
    status()


def main() -> None:
    parser = argparse.ArgumentParser(description="Check, open and import the Pexels test clips (manual download).")
    parser.add_argument("--open", action="store_true", help="open the Pexels page of every missing clip")
    parser.add_argument("--import", dest="import_dir", type=Path, help="move downloaded .mp4 files from this folder")
    args = parser.parse_args()
    if args.import_dir:
        import_from(args.import_dir)
        return
    missing = status()
    if args.open and missing:
        open_pages(missing)


if __name__ == "__main__":
    main()
