"""Deterministic synthetic inputs, explicitly not detector accuracy evidence."""

import argparse
from pathlib import Path

from app.demo import demo_rules, demo_zones
from app.models import Track, TrackFrame

SCENARIOS = {
    'exit_bag': (11, [5.0]),
    'walkthrough': (5, []),
    'short_bag': (6, []),
    'two_bags': (11, [5.0, 5.0]),
    'dropout': (11, [5.0]),
    'id_switch': (11, [5.0]),
    'reentry': (22, [5.0, 16.0]),
    'long_dropout': (15, [9.3]),
    'threshold_dropout': (11, [5.4]),
    'empty': (8, []),
    'chair': (11, [5.0]),
    'outside_reset': (13, [9.5]),
}


def synthetic_config(camera_id='cam_exit'):
    """An exit zone per synthetic camera, regardless of the live demo layout."""
    zone = demo_zones()[1].model_copy(update={
        'id': f'{camera_id}_exit', 'camera_id': camera_id})
    rule = demo_rules()[2].model_copy(update={'zone': zone.id})
    return [zone], [rule]


def scenario(name: str, camera_id='cam_exit') -> list[TrackFrame]:
    if name not in SCENARIOS:
        raise ValueError(f'Unknown synthetic scenario: {name}')
    duration, _ = SCENARIOS[name]
    frames = []
    for tick in range(duration * 10 + 1):
        ts = tick / 10
        tracks = []
        active = ts < 8
        if name == 'empty':
            active = False
        elif name == 'walkthrough':
            active = ts < 2
        elif name == 'short_bag':
            active = ts < 3
        elif name == 'reentry':
            active = ts < 8 or 11 <= ts < 19
        elif name == 'long_dropout':
            active = ts < 3 or 4.3 <= ts < 12
        elif name == 'dropout':
            active = ts < 8 and not 3 <= ts < 3.6
        elif name == 'threshold_dropout':
            active = ts < 8 and not 4.8 <= ts < 5.4
        elif name == 'outside_reset':
            active = ts < 10
        if active:
            bbox = (0.3, 0.3, 0.5, 0.7)
            if name == 'outside_reset' and 4 <= ts < 4.5:
                bbox = (0.01, 0.1, 0.1, 0.7)
            object_class = ('person' if name == 'walkthrough'
                            else 'chair' if name == 'chair' else 'backpack')
            tracks.append(Track(
                track_id=2 if name == 'id_switch' and ts >= 3 else 1,
                object_class=object_class, bbox=bbox, confidence=0.95))
            if name == 'two_bags':
                tracks.append(Track(track_id=2, object_class='backpack',
                                    bbox=(0.55, 0.3, 0.75, 0.7), confidence=0.9))
        frames.append(TrackFrame(camera_id=camera_id, ts=ts, tracks=tracks))
    return frames


def write_scenarios(directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in SCENARIOS:
        path = directory / f'{name}.tracks.jsonl'
        path.write_text(''.join(frame.model_dump_json() + '\n'
                                for frame in scenario(name)), encoding='utf-8')
        paths.append(path)
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='Output directory for synthetic JSONL')
    args = parser.parse_args()
    for path in write_scenarios(args.directory):
        print(path)


if __name__ == '__main__':
    main()
