"""Replay tracks through the temporal engine without cameras or AI models."""

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

from app.models import Rule, TrackFrame, Zone
from engine.engine import RuleEngine
from engine.fake_tracks import synthetic_config


def read_frames(path: Path):
    with path.open(encoding='utf-8') as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                yield TrackFrame.model_validate_json(line)
            except ValueError as exc:
                raise ValueError(f'{path}:{line_number}: invalid TrackFrame: {exc}') from exc


def replay(frames, zones=None, rules=None):
    """Accept interleaved cameras; enforce timestamp order separately per camera.

    Without an explicit config, use the documented synthetic exit zone. The fixed
    replay session IDs and UTC epoch make output repeatable. Those epoch times
    are placeholders, not actual incident dates.
    """
    if (zones is None) != (rules is None):
        raise ValueError('Provide both zones and rules, or neither')
    engines = {}
    alerts = []
    for tf in frames:
        if tf.camera_id not in engines:
            camera_zones, camera_rules = (synthetic_config(tf.camera_id)
                                          if zones is None else (zones, rules))
            engines[tf.camera_id] = RuleEngine(tf.camera_id, camera_zones, camera_rules,
                                               session_id='synthetic-replay')
        engine = engines[tf.camera_id]
        created_at = (datetime(1970, 1, 1, tzinfo=timezone.utc)
                      + timedelta(seconds=tf.ts)).isoformat().replace('+00:00', 'Z')
        engine.clock = lambda value=created_at: value
        try:
            _, new_alerts = engine.update(None, tf)
        except ValueError as exc:
            raise ValueError(f'{tf.camera_id} at {tf.ts}s: {exc}') from exc
        alerts.extend(new_alerts)
    for engine in engines.values():
        alerts.extend(engine.drain_verifications())
    return alerts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tracks', type=Path)
    parser.add_argument('--config', type=Path, help='JSON with zones and rules arrays')
    args = parser.parse_args()
    try:
        config = {}
        if args.config:
            data = json.loads(args.config.read_text(encoding='utf-8'))
            config = {'zones': [Zone.model_validate(z) for z in data['zones']],
                      'rules': [Rule.model_validate(r) for r in data['rules']]}
        alerts = replay(read_frames(args.tracks), **config)
        for alert in alerts:
            print(alert.model_dump_json())
        print(f'{len(alerts)} alert(s); track replay only, no visual verification', file=sys.stderr)
    except (ValueError, KeyError, OSError, NotImplementedError) as exc:
        parser.exit(2, f'Replay failed: {exc}\n')


if __name__ == '__main__':
    main()
