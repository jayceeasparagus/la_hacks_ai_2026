"""Export machine-readable approved schemas and validated example payloads."""

import argparse
import json
from pathlib import Path

from app.demo import demo_cameras, demo_rules, demo_zones
from app.models import Alert, Camera, CompileResult, Rule, RuleState, Track, TrackFrame, Verdict, Zone
from engine.alerts import obstruction_alert


def export(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    models = [Camera, Zone, Rule, CompileResult, TrackFrame, Verdict, RuleState, Alert]
    schemas = {model.__name__: model.model_json_schema() for model in models}
    examples = {
        'cameras': [camera.model_dump(mode='json') for camera in demo_cameras()],
        'zones': [zone.model_dump(mode='json') for zone in demo_zones()],
        'compile_result': CompileResult(rules=demo_rules()).model_dump(mode='json'),
        'rules': [rule.model_dump(mode='json') for rule in demo_rules()],
        'track_frame': TrackFrame.model_validate({
            'camera_id': 'cam_exit', 'ts': 5.4, 'tracks': [{
                'track_id': 12, 'object_class': 'backpack',
                'bbox': [0.3, 0.3, 0.5, 0.7], 'confidence': 0.95,
            }]}).model_dump(mode='json'),
        'verdict': Verdict(answer=None, confidence=0, reason='Bag is obscured').model_dump(),
    }
    state = RuleState(camera_id='cam_exit', rule_id='blocked_exit', track_id=12,
                      incident_id='example-incident', ts=5.4, elapsed_seconds=5.4,
                      duration_seconds=5, phase='alerted')
    alert = obstruction_alert(
        incident_id=state.incident_id, camera_id=state.camera_id, rule=demo_rules()[2],
        track=Track.model_validate(examples['track_frame']['tracks'][0]),
        ts=state.ts, elapsed=state.elapsed_seconds, confidence=0.95,
        zone_name='Emergency exit', created_at='2026-10-17T00:00:00Z')
    examples['rule_state'] = state.model_dump(mode='json')
    examples['alert'] = alert.model_dump(mode='json')
    examples['ws_alert'] = {'type': 'alert', 'data': examples['alert']}
    for filename, data in [('models.schema.json', schemas), ('examples.json', examples)]:
        (directory / filename).write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    export(parser.parse_args().directory)


if __name__ == '__main__':
    main()
