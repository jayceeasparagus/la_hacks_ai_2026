"""Render the construction-site example videos for the website.

    cd backend
    python -B ../demo/render_ppe_examples.py            # uses cached verdicts when present
    python -B ../demo/render_ppe_examples.py --refresh  # ask Gemini again

For each clip: Person 1's detector tracks (python -m vision.dump <clip>) give every worker's box.
Each worker seen long enough gets the real hard_hat and safety_vest checks (Person 2's verifier
questions, sent to Gemini on that worker's clearest crop). Verdicts are cached in
demo/ppe_verdicts.json, so re-rendering never calls Gemini again. The output is an H.264 MP4 plus a
poster image in frontend/public/examples/, playable on the website with no backend.

Wording stays neutral ("Hard hat: not seen"), never "violation": these are real people in stock
footage, and PolicyLens checks gear, never identity.
"""

import argparse
import base64
import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from dotenv import load_dotenv  # noqa: E402

from engine.crop import crop  # noqa: E402
from policy import llm  # noqa: E402
from policy.draft import structured_output_schema  # noqa: E402
from verify.prompts import QUESTIONS  # noqa: E402
from verify.verifier import VisionAnswer, encode_jpeg, to_verdict  # noqa: E402

CLIPS = {
    'construction_site': {
        'video': ROOT / 'clips/pexels/construction_workers_5434220.mp4',
        'tracks': ROOT / 'clips/pexels/construction_workers_5434220.tracks.jsonl',
        'zone': 'Construction zone',
        'where': 'in the construction zone',
        'credit': 'Pexels 5434220',
    },
    'warehouse': {
        'video': ROOT / 'clips/pexels/warehouse_4281236.mp4',
        'tracks': ROOT / 'clips/pexels/warehouse_4281236.tracks.jsonl',
        'zone': 'Warehouse floor',
        'where': 'on the warehouse floor',
        'credit': 'Pexels 4281236',
    },
}
CHECKS = ('hard_hat', 'safety_vest')
GEAR = {'hard_hat': 'Hard hat', 'safety_vest': 'Hi-vis vest'}
MIN_FRAMES = 20          # a worker must be tracked at least this long to be judged (skips detector blips)
MIN_HEIGHT_PX = 150      # ...and appear at least this tall at some point
OUT_WIDTH = 960
MAX_FPS = 25
VERDICTS = ROOT / 'demo' / 'ppe_verdicts.json'
OUT_DIR = ROOT / 'frontend' / 'public' / 'examples'

# RGB colours for Pillow
OK = (74, 201, 125)
MISSING = (255, 170, 40)
UNSURE = (170, 170, 170)


def load_tracks(path: Path) -> dict[int, list[dict]]:
    """frame index -> person tracks (Person 1's draft TrackFrame format)."""
    frames = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        tf = json.loads(line)
        frames[tf['frame_index']] = [t for t in tf['tracks'] if t['class_name'] == 'person']
    return frames


def main_workers(frames: dict[int, list[dict]], height: int) -> dict[int, tuple[int, list[float], float]]:
    """track id -> (frame index, bbox, score) of its clearest view, for workers worth judging."""
    seen, best = {}, {}
    for index, tracks in frames.items():
        for t in tracks:
            x1, y1, x2, y2 = t['bbox']
            score = (x2 - x1) * (y2 - y1) * t['conf']
            stats = seen.setdefault(t['track_id'], {'frames': 0, 'max_h': 0})
            stats['frames'] += 1
            stats['max_h'] = max(stats['max_h'], (y2 - y1) * height)
            if score > best.get(t['track_id'], (0, None, -1))[2]:
                best[t['track_id']] = (index, t['bbox'], score)
    return {tid: best[tid] for tid, s in seen.items() if s['frames'] >= MIN_FRAMES and s['max_h'] >= MIN_HEIGHT_PX}


def read_frame(video: Path, index: int) -> np.ndarray:
    capture = cv2.VideoCapture(str(video))
    capture.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, image = capture.read()
    capture.release()
    if not ok:
        raise RuntimeError(f'cannot read frame {index} of {video.name}')
    return image


def ask_gemini(image: np.ndarray, check: str) -> dict:
    """One verifier question with a generous timeout (offline rendering, not the live 4 s budget)."""
    jpeg = encode_jpeg(image)
    contents = [{'type': 'text', 'text': QUESTIONS[check]},
                {'type': 'image', 'data': base64.b64encode(jpeg).decode(), 'mime_type': 'image/jpeg'}]
    text = llm.call_structured(contents, structured_output_schema(VisionAnswer), model=llm.verify_model(),
                               timeout=90, thinking_level='minimal')
    raw = VisionAnswer.model_validate_json(text)
    verdict = to_verdict(raw)
    return {'answer': verdict.answer, 'confidence': round(verdict.confidence, 2), 'reason': verdict.reason}


def get_verdicts(refresh: bool) -> dict:
    cache = {} if refresh or not VERDICTS.exists() else json.loads(VERDICTS.read_text(encoding='utf-8'))
    jobs = []
    for name, clip in CLIPS.items():
        frames = load_tracks(clip['tracks'])
        height = int(cv2.VideoCapture(str(clip['video'])).get(cv2.CAP_PROP_FRAME_HEIGHT))
        for tid, (index, bbox, _) in sorted(main_workers(frames, height).items()):
            for check in CHECKS:
                key = f'{name}:{tid}:{check}'
                if key not in cache:
                    jobs.append((key, clip['video'], index, bbox, check))
    if jobs:
        llm.reset_breaker()
        print(f'Asking Gemini ({llm.verify_model()}) {len(jobs)} questions...')

        def run(job):
            key, video, index, bbox, check = job
            try:
                return key, {**ask_gemini(crop(read_frame(video, index), bbox), check), 'frame': index}
            except Exception as exc:
                return key, {'answer': None, 'confidence': 0.0, 'reason': f'no verdict ({type(exc).__name__})',
                             'frame': index, 'error': True}

        with ThreadPoolExecutor(max_workers=4) as pool:
            for key, verdict in pool.map(run, jobs):
                cache[key] = verdict
                print(f'  {key}: {verdict["answer"]} ({verdict["confidence"]}) {verdict["reason"]}')
        VERDICTS.write_text(json.dumps(cache, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return cache


def font(size: int, bold: bool = False):
    for name in (('segoeuib.ttf', 'arialbd.ttf') if bold else ('segoeui.ttf', 'arial.ttf')):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def status(verdicts: dict, name: str, tid: int) -> dict[str, bool | None] | None:
    keys = {check: f'{name}:{tid}:{check}' for check in CHECKS}
    if not all(k in verdicts for k in keys.values()):
        return None
    return {check: verdicts[k]['answer'] for check, k in keys.items()}


def colour(gear: dict[str, bool | None]) -> tuple[int, int, int]:
    if all(v is True for v in gear.values()):
        return OK
    if any(v is False for v in gear.values()):
        return MISSING
    return UNSURE


def _overlap(a, b) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def draw(image: np.ndarray, tracks: list[dict], verdicts: dict, name: str, clip: dict, summary: str,
         fonts: dict, judged: set[int]) -> np.ndarray:
    pil = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    canvas = ImageDraw.Draw(pil, 'RGBA')
    w, h = pil.size
    top_limit, bottom_limit = 14 + fonts['banner'].size + 22, h - fonts['small'].size - 32  # keep clear of banner and footer
    people = []
    for t in tracks:
        box = (t['bbox'][0] * w, t['bbox'][1] * h, t['bbox'][2] * w, t['bbox'][3] * h)
        if t['track_id'] in judged:
            people.append((box, status(verdicts, name, t['track_id'])))
        else:
            canvas.rectangle(box, outline=(255, 255, 255, 70), width=1)  # seen, but not long enough to judge
    people.sort(key=lambda p: (p[0][2] - p[0][0]) * (p[0][3] - p[0][1]), reverse=True)  # nearest first
    for box, gear in people:
        canvas.rectangle(box, outline=colour(gear) + (255,), width=3)

    line_h = fonts['label'].size + 8
    placed: list[tuple[float, float, float, float]] = []
    # each worker's head region (top quarter of the box) must stay visible: it's where the hard hat is
    heads = [(b[0], b[1], b[2], b[1] + (b[3] - b[1]) * 0.25) for b, _ in people]
    for index, ((x1, y1, x2, y2), gear) in enumerate(people):
        lines = [(f'{GEAR[check]}: ' + {True: 'yes', False: 'not seen', None: 'unclear'}[v],
                  OK if v is True else MISSING if v is False else UNSURE) for check, v in gear.items()]
        box_w = max(canvas.textlength(text, font=fonts['label']) for text, _ in lines) + 34
        box_h = line_h * len(lines) + 6
        left = min(max(0.0, x1), w - box_w)
        # above the box, inside its top, then below it; first spot that collides with no other label
        candidates = [(left, y1 - box_h - 4), (min(x2 + 6, w - box_w), y1), (max(0.0, x1 - box_w - 6), y1),
                      (left + 4, y1 + (y2 - y1) * 0.3), (left, y2 + 4)]
        rects = [(cx, min(max(cy, top_limit), bottom_limit - box_h), cx + box_w, min(max(cy, top_limit), bottom_limit - box_h) + box_h)
                 for cx, cy in candidates]
        others = [head for i, head in enumerate(heads) if i != index]
        rect = min(rects, key=lambda r: sum(_overlap(r, p) for p in placed) + 3 * sum(_overlap(r, hd) for hd in others))
        placed.append(rect)
        canvas.rounded_rectangle(rect, 6, fill=(12, 12, 14, 215))
        for i, (text, dot) in enumerate(lines):
            y = rect[1] + 4 + i * line_h
            canvas.ellipse((rect[0] + 9, y + line_h / 2 - 5, rect[0] + 17, y + line_h / 2 + 3), fill=dot + (255,))
            canvas.text((rect[0] + 24, y + 1), text, font=fonts['label'], fill=(240, 238, 232))
    banner = f'Rule: everyone {clip["where"]} wears a hard hat and a hi-vis vest'
    canvas.rounded_rectangle((14, 14, 28 + canvas.textlength(banner, font=fonts['banner']), 14 + fonts['banner'].size + 16),
                             8, fill=(12, 12, 14, 200))
    canvas.text((22, 20), banner, font=fonts['banner'], fill=(240, 238, 232))
    foot = f'WatchDog · {summary} · footage: {clip["credit"]}'
    tw = canvas.textlength(foot, font=fonts['small'])
    canvas.rounded_rectangle((w - tw - 30, h - fonts['small'].size - 26, w - 14, h - 14), 6, fill=(12, 12, 14, 180))
    canvas.text((w - tw - 22, h - fonts['small'].size - 22), foot, font=fonts['small'], fill=(200, 198, 192))
    return cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)


def render(name: str, clip: dict, verdicts: dict) -> None:
    frames = load_tracks(clip['tracks'])
    capture = cv2.VideoCapture(str(clip['video']))
    fps = capture.get(cv2.CAP_PROP_FPS) or 25
    step = max(1, round(fps / MAX_FPS))
    width, height = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    size = (OUT_WIDTH, round(height * OUT_WIDTH / width) // 2 * 2)
    judged = [tid for tid in main_workers(frames, height) if status(verdicts, name, tid) is not None]
    gear = [status(verdicts, name, tid) for tid in judged]
    ok = sum(all(v is True for v in g.values()) for g in gear)
    missing = sum(any(v is False for v in g.values()) for g in gear)
    unclear = len(judged) - ok - missing
    summary = f'{len(judged)} workers checked: {ok} full gear, {missing} missing gear' + (f', {unclear} unclear' if unclear else '')
    fonts = {'label': font(15, bold=True), 'banner': font(17, bold=True), 'small': font(13)}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f'{name}.mp4'
    writer = VideoOut(out, fps / step, size)
    poster, poster_score, index = None, -1, 0
    while True:
        ok_read, image = capture.read()
        if not ok_read:
            break
        if index % step == 0:
            tracks = frames.get(index, [])
            framed = draw(cv2.resize(image, size, interpolation=cv2.INTER_AREA), tracks, verdicts, name, clip, summary, fonts,
                          set(judged))
            writer.write(framed)
            score = sum(1 for t in tracks if t['track_id'] in judged)
            if score > poster_score:
                poster, poster_score = framed, score
        index += 1
    writer.release()
    capture.release()
    cv2.imwrite(str(OUT_DIR / f'{name}.jpg'), poster, [cv2.IMWRITE_JPEG_QUALITY, 85])
    check = cv2.VideoCapture(str(out))
    codec = int(check.get(cv2.CAP_PROP_FOURCC)).to_bytes(4, 'little').decode(errors='replace')
    print(f'{out.name}: {int(check.get(cv2.CAP_PROP_FRAME_COUNT))} frames at {fps / step:.0f} fps, codec {codec}, '
          f'{out.stat().st_size / 1e6:.1f} MB; {summary}')
    check.release()


class VideoOut:
    """Browser-friendly H.264: ffmpeg/libx264 (small files, faststart) when installed, else OpenCV's avc1."""

    def __init__(self, path: Path, fps: float, size: tuple[int, int]):
        self.ffmpeg = shutil.which('ffmpeg')
        if self.ffmpeg:
            self.proc = subprocess.Popen(
                [self.ffmpeg, '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'bgr24',
                 '-s', f'{size[0]}x{size[1]}', '-r', f'{fps:.3f}', '-i', '-', '-an', '-c:v', 'libx264',
                 '-preset', 'slow', '-crf', '28', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(path)],
                stdin=subprocess.PIPE)
        else:
            self.writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'avc1'), fps, size)
            if not self.writer.isOpened():
                raise SystemExit('No H.264 encoder: install ffmpeg (browsers need H.264 for <video>)')

    def write(self, frame: np.ndarray) -> None:
        if self.ffmpeg:
            self.proc.stdin.write(np.ascontiguousarray(frame).tobytes())
        else:
            self.writer.write(frame)

    def release(self) -> None:
        if self.ffmpeg:
            self.proc.stdin.close()
            if self.proc.wait() != 0:
                raise SystemExit('ffmpeg failed to encode the example video')
        else:
            self.writer.release()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--refresh', action='store_true', help='ignore cached verdicts and ask Gemini again')
    args = parser.parse_args()
    load_dotenv(ROOT / '.env')
    verdicts = get_verdicts(args.refresh)
    for name, clip in CLIPS.items():
        render(name, clip, verdicts)


if __name__ == '__main__':
    main()
