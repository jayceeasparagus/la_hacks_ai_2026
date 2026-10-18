"""Generate explicitly synthetic recorded inputs for the Part A offline demo."""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from app.demo import demo_rules, demo_zones
from app.models import Track
from engine.fake_tracks import scenario


def write_demo(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, camera in [('exit', 'cam_exit'), ('entrance', 'cam_entrance')]:
        video_path = directory / f'{name}.mp4'
        tracks_path = directory / f'{name}.tracks.jsonl'
        video = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*'mp4v'), 10, (480, 270))
        if not video.isOpened():
            video.release()
            raise ValueError('Demo MP4 encoder unavailable')
        frames = scenario('exit_bag', camera)
        try:
            for frame in frames:
                if name == 'entrance' and frame.tracks:
                    frame.tracks.append(Track(track_id=2, object_class='camera',
                        bbox=(0.55, 0.3, 0.75, 0.7), confidence=0.9))
                image = np.full((270, 480, 3), 80, np.uint8)
                for track in frame.tracks:
                    x1, y1, x2, y2 = track.bbox
                    cv2.rectangle(image, (round(x1 * 480), round(y1 * 270)),
                                  (round(x2 * 480), round(y2 * 270)), (100, 180, 100), -1)
                    cv2.putText(image, track.object_class, (round(x1 * 480), round(y1 * 270) + 22),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
                cv2.putText(image, 'SYNTHETIC TRACK INPUT - NOT DETECTOR OUTPUT', (8, 245),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
                video.write(image)
        finally:
            video.release()
        tracks_path.write_text(''.join(frame.model_dump_json() + '\n' for frame in frames), encoding='utf-8')
        paths.extend([video_path, tracks_path])
    config = directory / 'config.json'
    config.write_text(json.dumps({
        'zones': [zone.model_dump(mode='json') for zone in demo_zones()],
        'rules': [rule.model_dump(mode='json') for rule in demo_rules()],
    }, indent=2) + '\n', encoding='utf-8')
    return [*paths, config]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    for path in write_demo(parser.parse_args().directory):
        print(path)


if __name__ == '__main__':
    main()
