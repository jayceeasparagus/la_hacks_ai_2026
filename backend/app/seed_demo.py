"""Create a fresh offline backend demo without replacing existing settings."""

import argparse
import os
from pathlib import Path

from app.demo import demo_cameras, demo_rules, demo_zones
from engine.demo_recording import write_demo
from store.config import ConfigurationStore


def seed_demo(root):
    root = Path(root).resolve()
    if (root / 'config.json').exists():
        raise FileExistsError('Configuration already exists; choose a fresh data directory')
    clips = root / 'demo-clips'
    write_demo(clips)
    cameras = demo_cameras()
    cameras[0].source = f'clip:{clips / "entrance.mp4"}'
    cameras[1].source = f'clip:{clips / "exit.mp4"}'
    return ConfigurationStore(root / 'config.json').replace(
        cameras=cameras, zones=demo_zones(), rules=demo_rules())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path(
        os.environ.get('POLICYLENS_DATA_DIR') or Path(__file__).resolve().parents[1] / 'store/runtime'))
    args = parser.parse_args()
    try:
        seed_demo(args.data_dir)
    except (ValueError, OSError) as exc:
        parser.exit(2, f'Demo setup failed: {exc}\n')
    print(f'DEMO seeded in {args.data_dir.resolve()}; synthetic video, saved tracks, unclear verifier stub.')
    print('Start: uvicorn app.main:app --host 127.0.0.1 --port 8000')


if __name__ == '__main__':
    main()
