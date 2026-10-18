"""Convert CAVIAR ground-truth XML into approved TrackFrame JSONL for replay over the real video.

    python -B ../eval/caviar_tracks.py ../clips/caviar/lb1gt.xml --video ../clips/caviar/LeftBag.mpg \
        --camera-id cam_lobby_east --out ../clips/caviar/LeftBag.gt.tracks.jsonl

CAVIAR (EC Funded CAVIAR project / IST 2001 37540, CC BY-SA) labels every object per frame with a
centre/size box and a role. The object whose role is "leaving object" is the left bag (class
backpack); every other object is a person. Boxes are hand labels, so confidence is 1.0, and each
CAVIAR object id becomes a stable track id. Every video frame gets a TrackFrame, including empty
ones, so the engine sees absences. This is ground truth, not detector output: it shows how the
rules behave on real footage; detector accuracy needs Person 1's pipeline on the same clips.
"""

import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import cv2

BAG_ROLES = {'leaving object'}


def convert(gt_path: Path, video: Path, camera_id: str) -> list[dict]:
    capture = cv2.VideoCapture(str(video))
    fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
    width, height = capture.get(cv2.CAP_PROP_FRAME_WIDTH), capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
    count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    capture.release()
    if not width or not height:
        raise SystemExit(f'cannot read {video}')

    labels: dict[int, list[dict]] = {}
    for frame in ET.parse(gt_path).getroot().iter('frame'):
        tracks = []
        for obj in frame.iter('object'):
            box = obj.find('box')
            xc, yc, w, h = (float(box.get(key)) for key in ('xc', 'yc', 'w', 'h'))
            x1, y1 = max(0.0, (xc - w / 2) / width), max(0.0, (yc - h / 2) / height)
            x2, y2 = min(1.0, (xc + w / 2) / width), min(1.0, (yc + h / 2) / height)
            if x2 <= x1 or y2 <= y1:
                continue
            role = (obj.findtext('.//role') or '').strip()
            tracks.append({'track_id': int(obj.get('id')),
                           'object_class': 'backpack' if role in BAG_ROLES else 'person',
                           'bbox': [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)],
                           'confidence': 1.0})
        labels[int(frame.get('number'))] = tracks
    total = max(count, max(labels, default=-1) + 1)
    return [{'camera_id': camera_id, 'ts': round(index / fps, 4), 'tracks': labels.get(index, [])}
            for index in range(total)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('ground_truth', type=Path)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--camera-id', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    frames = convert(args.ground_truth, args.video, args.camera_id)
    args.out.write_text(''.join(json.dumps(f) + '\n' for f in frames), encoding='utf-8')
    bags = {t['track_id'] for f in frames for t in f['tracks'] if t['object_class'] == 'backpack'}
    people = {t['track_id'] for f in frames for t in f['tracks'] if t['object_class'] == 'person'}
    print(f'{args.out}: {len(frames)} frames, {len(people)} people, {len(bags)} left bag(s)')


if __name__ == '__main__':
    main()
