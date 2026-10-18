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
