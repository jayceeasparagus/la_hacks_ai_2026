"""Cache real Gemini verdicts for a demo camera, so the live demo is instant and works offline.

    cd backend
    python -B ../demo/cache_verdicts.py --scene ../demo/scenes/site_safety.json --camera cam_plaza \\
        --clip plaza --check jeans --out ../demo/plaza_verdicts.json

It replays the camera's tracks through the real RuleEngine (with a rule for the check on every person)
to list exactly the tracks the live demo would verify, crops each track's clearest view from the video,
and asks the verifier the same question it asks live (verify.verify_crop: same prompt, confidence
threshold and rate limit). Answers are saved as "<clip>:<track_id>:<check>" for app/verdicts.py and
the scene's cached_verdicts. Keys already in the file are skipped, so a rerun only fills gaps; failed
calls are saved with "error": true and asked again live. Crops under 40 px are saved as unclear.
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from dotenv import load_dotenv  # noqa: E402

from app.models import Rule, Verdict  # noqa: E402
from app.scenes import read_scene  # noqa: E402
from engine.crop import crop  # noqa: E402
from engine.engine import InlineExecutor, RuleEngine, crop_score  # noqa: E402
from engine.replay import read_frames  # noqa: E402
from verify.prompts import CHECK_FOR_ATTRIBUTE  # noqa: E402
from verify.verifier import MIN_SIDE_PX, verify_crop  # noqa: E402

ATTRIBUTE_FOR_CHECK = {check: attribute for attribute, check in CHECK_FOR_ATTRIBUTE.items()}
RETRIES = 3


def requested_tracks(camera_id: str, zones, frames, check: str) -> list[int]:
    """Track ids the live engine would verify for `check`, over two loops of the clip."""
    zone = next(z for z in zones if z.camera_id == camera_id)
    attribute = ATTRIBUTE_FOR_CHECK[check]
    rule = Rule(id=attribute, name=attribute, type='object_attribute', objects=['person'], zone=zone.id,
                attribute={'name': attribute, 'expected': True}, duration_seconds=1.0, severity='review')
    asked: list[int] = []

    def lookup(track_id, asked_check):
        if track_id not in asked:
            asked.append(track_id)
        return Verdict(answer=None, confidence=0, reason='listing only')

    engine = RuleEngine(camera_id, zones, [rule], executor=InlineExecutor(), verdict_lookup=lookup,
                        verifier=lambda image, c: Verdict(answer=None, confidence=0, reason='unused'))
    period = frames[-1].ts - frames[0].ts + 0.1
    for loop in range(2):
        for tf in frames:
            engine.update(None, tf.model_copy(update={'camera_id': camera_id, 'ts': tf.ts + loop * period}))
    return asked


def best_views(frames, track_ids: set[int], fps: float) -> dict[int, tuple[int, tuple]]:
    """track id -> (video frame index, bbox) of its clearest, most central view."""
    best: dict[int, tuple[float, int, tuple]] = {}
    start = frames[0].ts
    for tf in frames:
        for track in tf.tracks:
            if track.track_id in track_ids and track.object_class == 'person':
                score = crop_score(track)
                if score > best.get(track.track_id, (-1.0,))[0]:
                    best[track.track_id] = (score, round((tf.ts - start) * fps), track.bbox)
    return {tid: (index, bbox) for tid, (_, index, bbox) in best.items()}


def read_frame(video: Path, index: int):
    capture = cv2.VideoCapture(str(video))
    capture.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, image = capture.read()
    capture.release()
    if not ok:
        raise RuntimeError(f'cannot read frame {index} of {video.name}')
    return image


def ask(image, check: str) -> dict:
    verdict = Verdict(answer=None, confidence=0, reason='not asked')
    for _ in range(RETRIES):
        verdict = verify_crop(image, check)
        if verdict.reason not in ('verification busy', 'verification timed out', 'verification unavailable'):
            return {'answer': verdict.answer, 'confidence': round(verdict.confidence, 2), 'reason': verdict.reason}
    return {'answer': None, 'confidence': 0.0, 'reason': f'no verdict ({verdict.reason})', 'error': True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--scene', type=Path, required=True)
    parser.add_argument('--camera', required=True, help='camera id in the scene (a loop: or replay: source)')
    parser.add_argument('--clip', required=True, help='clip name used in the cache keys')
    parser.add_argument('--check', required=True, choices=sorted(ATTRIBUTE_FOR_CHECK))
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    load_dotenv(ROOT / '.env')

    scene = read_scene(args.scene)
    camera = next(c for c in scene.cameras if c.id == args.camera)
    tracks_path, _, video = camera.source.partition(':')[2].partition('@')
    frames = list(read_frames(Path(tracks_path)))
    capture = cv2.VideoCapture(video)
    fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
    capture.release()

    asked = requested_tracks(args.camera, scene.zones, frames, args.check)
    cache = json.loads(args.out.read_text(encoding='utf-8')) if args.out.exists() else {}
    todo = [tid for tid in asked if f'{args.clip}:{tid}:{args.check}' not in cache]
    views = best_views(frames, set(todo), fps)
    print(f'{len(asked)} tracks would be checked; {len(todo)} not cached yet')

    def run(tid: int):
        index, bbox = views[tid]
        image = crop(read_frame(Path(video), index), bbox)
        if min(image.shape[:2]) < MIN_SIDE_PX:
            return tid, {'answer': None, 'confidence': 0.0, 'reason': 'object too small to judge', 'frame': index}
        return tid, {**ask(image, args.check), 'frame': index}

    done = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for tid, verdict in pool.map(run, [tid for tid in todo if tid in views]):
            cache[f'{args.clip}:{tid}:{args.check}'] = verdict
            done += 1
            print(f'  [{done}/{len(todo)}] {args.clip}:{tid}: {verdict["answer"]} ({verdict["confidence"]}) {verdict["reason"]}')
            if done % 20 == 0:
                args.out.write_text(json.dumps(cache, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    args.out.write_text(json.dumps(cache, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    answers = [cache[f'{args.clip}:{tid}:{args.check}']['answer'] for tid in asked if f'{args.clip}:{tid}:{args.check}' in cache]
    print(f'saved {len(cache)} entries to {args.out}: yes {answers.count(True)}, no {answers.count(False)}, '
          f'unclear {answers.count(None)}')


if __name__ == '__main__':
    main()
