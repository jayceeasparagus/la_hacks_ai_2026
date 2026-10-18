"""Replay tracks through the temporal engine without cameras or AI models."""

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

from app.models import Rule, TrackFrame, Verdict, Zone
from engine.engine import InlineExecutor, RuleEngine
from engine.fake_tracks import synthetic_config

NO_FRAME = Verdict(answer=None, confidence=0, reason='no video frame in track replay')


def no_frame_verifier(image, check: str) -> Verdict:
    """Track files carry no pixels, so an attribute can never be judged offline."""
    return NO_FRAME


def _draft(line: str) -> dict | None:
    """A line in Person 1's draft format (`python -m vision.dump`), or None."""
    try:
        data = json.loads(line)
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get('tracks'), list):
        return None
    if 'frame_index' in data or any(isinstance(t, dict) and 'class_name' in t for t in data['tracks']):
        return data
    return None


def read_frames(path: Path):
    """Approved TrackFrames, or Person 1's draft lines converted through app.adapter.

    Draft tracks with unsupported classes or bad boxes are dropped, exactly as for live cameras.
    """
    from app.adapter import ContractAdapter
    adapter = None
    with path.open(encoding='utf-8') as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                frame = TrackFrame.model_validate_json(line)
            except ValueError as exc:
                draft = _draft(line)
                if draft is None:
                    raise ValueError(f'{path}:{line_number}: invalid TrackFrame: {exc}') from exc
                first = adapter is None
                try:
                    adapter = adapter or ContractAdapter(str(draft.get('camera_id') or 'replay'))
                    frame, restarted = adapter.convert(draft)
                except ValueError as error:
                    raise ValueError(f'{path}:{line_number}: invalid draft TrackFrame: {error}') from error
                if restarted and not first:
                    raise ValueError(f'{path}:{line_number}: timestamps go backwards')
                if frame is None:
                    continue  # repeated timestamp
            yield frame


def replay(frames, zones=None, rules=None, *, verifier=None):
    """Accept interleaved cameras; enforce timestamp order separately per camera.

    Without an explicit config, use the documented synthetic exit zone. The fixed
    replay session IDs and UTC epoch make output repeatable. Those epoch times
    are placeholders, not actual incident dates. Verification runs inline, so a
    verdict is reported at the next frame (or the final drain). Without frames
    the default verifier answers unclear: attribute incidents need manual review.
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
                                               session_id='synthetic-replay',
                                               verifier=verifier or no_frame_verifier,
                                               executor=InlineExecutor())
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
        alerts.extend(engine.drain())
        engine.close()
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
        print(f'{len(alerts)} alert(s); track replay only: no video frames, so attribute '
              'rules become manual-review alerts', file=sys.stderr)
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(2, f'Replay failed: {exc}\n')


if __name__ == '__main__':
    main()
