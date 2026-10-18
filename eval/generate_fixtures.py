"""Reproducible, visibly synthetic clips for cases.csv; not real-world footage."""

from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

import cv2
import numpy as np
from engine.demo_recording import write_demo
from engine.fake_tracks import SCENARIOS, scenario, synthetic_config


def generate(root=None):
    root = Path(root or Path(__file__).with_name('generated') / 'evaluation')
    root.mkdir(parents=True, exist_ok=True)
    zones, rules = synthetic_config()
    (root / 'temporal.json').write_text(json.dumps({
        'zones': [zone.model_dump(mode='json') for zone in zones],
        'rules': [rule.model_dump(mode='json') for rule in rules]}, indent=2), encoding='utf-8')
    for name in SCENARIOS:
        frames = scenario(name)
        writer = cv2.VideoWriter(str(root / f'{name}.mp4'), cv2.VideoWriter_fourcc(*'mp4v'), 10, (320, 180))
        if not writer.isOpened():
            writer.release()
            raise ValueError('Synthetic fixture encoder unavailable')
        try:
            for frame in frames:
                image = np.full((180, 320, 3), 80, np.uint8)
                for track in frame.tracks:
                    x1, y1, x2, y2 = track.bbox
                    cv2.rectangle(image, (round(x1 * 320), round(y1 * 180)),
                                  (round(x2 * 320), round(y2 * 180)), (100, 180, 100), -1)
                cv2.putText(image, 'SYNTHETIC EVALUATION INPUT', (5, 165),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255,255,255), 1)
                writer.write(image)
        finally:
            writer.release()
        (root / f'{name}.tracks.jsonl').write_text(''.join(frame.model_dump_json() + '\n' for frame in frames), encoding='utf-8')
    write_demo(root / 'entrance')
    return root


if __name__ == '__main__':
    print(generate())
