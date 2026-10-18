# Footage and dataset sources

The videos and datasets are not committed (they're large; see `.gitignore`). Re-download them
from these pages. Each was downloaded by hand on 2026-10-17. Licenses are quoted from the source
pages on that date; re-check before publishing anything.

## Videos (`clips/`)

| File | Source | License | Used for |
| --- | --- | --- | --- |
| `caviar/LeftBag.mpg`, `lb1gt.xml` | [CAVIAR LeftBag](https://homepages.inf.ed.ac.uk/rbf/CAVIARDATA1/) | CC BY-SA. Credit "EC Funded CAVIAR project/IST 2001 37540" | Lobby scene: bag left on the exit walkway |
| `caviar/LeftBag_AtChair.mpg`, `lb2gt.xml` | same page | CC BY-SA | Lobby scene: bag left at the seating area |
| `caviar/LeftBag_PickedUp.mpg`, `lbpugt.xml` | same page | CC BY-SA | Lobby scene: bag left at the reception desk, then picked up |
| `pexels/clear_tote_7762512.mp4` | [Pexels 7762512](https://www.pexels.com/video/a-woman-carrying-a-clear-tote-bag-7762512/) | [Pexels License](https://www.pexels.com/license/) | Venue scene: clear bag (should pass) |
| `pexels/shoulder_camera_16612791.mp4` | [Pexels 16612791](https://www.pexels.com/video/a-man-with-a-camera-on-his-shoulder-16612791/) | Pexels License | Venue scene: professional camera |
| `pexels/phones_concert_12719510.mp4` | [Pexels 12719510](https://www.pexels.com/video/fans-recording-concert-with-smartphones-12719510/) | Pexels License | Venue scene: phones (must not trigger) |
| `pexels/campus_lobby_38469386.mp4` | [Pexels 38469386](https://www.pexels.com/video/modern-university-campus-lobby-with-people-walking-38469386/) | Pexels License | Tracking scene: many people, no false alerts |
| `pexels/construction_workers_5434220.mp4` | [Pexels 5434220](https://www.pexels.com/video/back-view-of-workers-walking-in-construction-site-5434220/) | Pexels License | Construction scene: workers in safety gear |
| `pexels/warehouse_4281236.mp4` | [Pexels 4281236](https://www.pexels.com/video/men-working-in-a-warehouse-4281236/) | Pexels License | Construction scene: warehouse floor |

The Pexels files are the 720p renditions. Pexels allows free use with no attribution required,
but identifiable people must not be shown "in a bad or offensive light". The Pexels and Pixabay
terms also forbid automated scraping, so download by hand only.

## Vision test clips (`clips/pexels/`, Person 1)

Used by `backend/vision/test_zones.json`, `python -m vision.evidence_run` and `python -m vision.dump`.
Download each by hand (Free download, 1080p). `python -m vision.fetch_test_clips` lists what's missing,
`--open` opens those pages, and `--import <downloads folder>` renames and moves the files into place.
It never downloads anything itself: Pexels' terms forbid automated downloading (Section 8) and
redistributing the videos on their own (Section 5). On 2026-10-18 the team chose to check in the clips
the demo scenes use (not the annotated renders) so teammates can run the demo from a clone; the repo is
public, so revisit that before sharing it widely.

| File | Source | License | Used for |
| --- | --- | --- | --- |
| `pexels/gate_man_ticket.mp4` | [Pexels 7251544](https://www.pexels.com/video/man-passing-a-ticket-gate-7251544/) | Pexels License | single-lane turnstile: the ideal choke point |
| `pexels/gate_pass_cards.mp4` | [Pexels 7952194](https://www.pexels.com/video/people-swiping-their-pass-cards-before-entering-7952194/) | Pexels License | queue at turnstiles, shoulder bag |
| `pexels/gate_woman_metro.mp4` | [Pexels 11565901](https://www.pexels.com/video/woman-walking-through-gate-at-metro-station-11565901/) | Pexels License | handheld; whole-frame zone |
| `pexels/gate_subway_turnstile.mp4` | [Pexels 39617498](https://www.pexels.com/video/modern-subway-turnstile-entry-scene-39617498/) | Pexels License | wider turnstile row, backpacks |
| `pexels/gate_nyc_turnstile.mp4` | [Pexels 16967317](https://www.pexels.com/video/the-everyday-act-of-walking-through-a-subway-turnstyle-in-new-york-city-the-video-is-silent-allowing-the-viewer-to-focus-on-the-visuals-of-the-scene-the-turnstyle-is-a-metal-structure-w-16967317/) | Pexels License | handheld walk through gates |
| `pexels/ppe_workers_walking.mp4` | [Pexels 5434223](https://www.pexels.com/video/workers-walking-in-construction-site-5434223/) | Pexels License | helmets and vests from behind |
| `pexels/ppe_group_walking.mp4` | [Pexels 8965526](https://www.pexels.com/video/construction-workers-walking-at-the-construction-site-8965526/) | Pexels License | helmets and vests walking toward the camera |
| `pexels/ppe_worker_entering.mp4` | [Pexels 5434217](https://www.pexels.com/video/a-construction-worker-entering-a-building-basement-5434217/) | Pexels License | one worker at an entrance |
| `pexels/stadium_entrance_gameday.mp4` | [Pexels 39239779](https://www.pexels.com/video/energetic-crowd-at-stadium-entrance-on-game-day-39239779/) | Pexels License | dense crowd (person threshold) |
| `pexels/stadium_fans_rabat.mp4` | [Pexels 34686011](https://www.pexels.com/video/fans-walk-to-modern-stadium-in-rabat-morocco-34686011/) | Pexels License | crowd walking to a stadium, backpacks |
| `pexels/wembley_station_entrance.mp4` | [Pexels 3405719](https://www.pexels.com/video/wembley-park-station-entrance-3405719/) | Pexels License | far, night-time plaza |
| `pexels/hotel_luggage_enter.mp4` | [Pexels 39596352](https://www.pexels.com/video/travelers-with-luggage-enter-a-modern-hotel-39596352/) | Pexels License | suitcases; carried-object timer pause |
| `pexels/airport_couple_enter.mp4` | [Pexels 7423654](https://www.pexels.com/video/couple-entering-a-airport-7423654/) | Pexels License | two people entering; held-object exit check |
| `pexels/airport_checkpoint_walkthrough.mp4` | [Pexels 27778672](https://www.pexels.com/video/a-security-checkpoint-at-an-airport-with-people-walking-through-27778672/) | Pexels License | busy checkpoint |
| `pexels/airport_checkpoint_busy.mp4` | [Pexels 32654547](https://www.pexels.com/video/busy-airport-terminal-security-checkpoint-scene-32654547/) | Pexels License | corridor choke point, handbags |
| `pexels/concert_fans_phones.mp4` | [Pexels 12719510](https://www.pexels.com/video/fans-recording-concert-with-smartphones-12719510/) | Pexels License | phones in a dark crowd |
| `pexels/concert_man_filming.mp4` | [Pexels 12695730](https://www.pexels.com/video/man-filming-concert-12695730/) | Pexels License | one phone held up (not a pro camera) |
| `pexels/street_smartphones.mp4` | [Pexels 39102147](https://www.pexels.com/video/busy-street-life-with-people-using-smartphones-39102147/) | Pexels License | phones in daylight |
| `pexels/walking_phone_sidewalk.mp4` | [Pexels 7867420](https://www.pexels.com/video/man-holding-a-cellphone-while-walking-on-the-sidewalk-7867420/) | Pexels License | phone and bag in hand |

## Dataset (`datasets/`)

| Folder | Source | License | Used for |
| --- | --- | --- | --- |
| `ppe/construction_site_safety/` | [Construction Site Safety (Kaggle, from Roboflow Universe)](https://www.kaggle.com/datasets/snehilsanyal/construction-site-safety-image-dataset-roboflow) | CC BY 4.0. Credit Roboflow Universe Projects and the Kaggle uploader | Hard-hat and vest crops for `verify.eval` |
| `verify_crops/` | built with `python -m verify.ppe_crops` from the test and valid splits | CC BY 4.0, derived from the above | 30 crops each: hard_hat yes/no, safety_vest yes/no |

The dataset's `source_files/` folder holds YouTube-sourced videos with unclear rights. Don't use
them in public material.

## Demo-video credits slide (suggested)

- Lobby footage: EC Funded CAVIAR project/IST 2001 37540 (CC BY-SA). Any edited video that
  includes it is arguably share-alike as well.
- Stock footage: Pexels creators (Pexels License).
- PPE evaluation images: Roboflow Universe "Construction Site Safety" (CC BY 4.0).

For footage of real people:
- Use neutral on-screen wording ("bag in exit zone", "review: camera"), never "suspicious person".
- Consider blurring faces.
- PolicyLens never identifies anyone.
