"""Evaluate recorded cases; offline fixtures never imply detector accuracy."""

import argparse
import csv
import json
import math
from pathlib import Path
import sys
import time

BACKEND = Path(__file__).resolve().parents[1] / 'backend'
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.models import Camera, Rule, Verdict, Zone
from app.sources import VisionSource
from engine.clip_replay import replay_clip
from engine.engine import RuleEngine
from engine.replay import read_frames
from engine.verification import StubVerifier, VerificationScheduler


def score(alerts, windows):
    remaining = set(range(len(windows)))
    correct, false, duplicates, source_delays, matches = 0, 0, 0, [], []
    seen = set()
    for alert in sorted(alerts, key=lambda item: (item.ts, item.id)):
        if alert.incident_id in seen:
            duplicates += 1
            continue
        seen.add(alert.incident_id)
        eligible = [index for index in sorted(remaining)
                    if windows[index][0] - 1e-6 <= alert.ts <= windows[index][1] + 1e-6]
        if eligible:
            index = eligible[0]
            remaining.remove(index)
            correct += 1
            source_delays.append(max(0, alert.ts - windows[index][0]))
            matches.append((alert.id, index))
        elif any(start - 1e-6 <= alert.ts <= end + 1e-6 for start, end in windows):
            duplicates += 1
        else:
            false += 1
    return {'correct_detections': correct, 'false_alerts': false,
            'missed_events': len(remaining), 'duplicate_alerts': duplicates,
            'source_delays': source_delays, 'matches': matches}


def load_cases(path):
    with Path(path).open(newline='', encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream))
    required = {'case_id','clip','tracks','config','camera_id','rule','expected_count',
                'expected_windows','stub_bag','stub_camera'}
    if not rows or any(not required.issubset(row) for row in rows):
        raise ValueError('Cases file is empty or missing required columns')
    if len({row['case_id'] for row in rows}) != len(rows):
        raise ValueError('Case IDs must be unique')
    for row in rows:
        windows = json.loads(row['expected_windows'])
        if not isinstance(windows, list) or len(windows) != int(row['expected_count']) or any(
                not isinstance(window, list) or len(window) != 2 or any(not isinstance(value, (int,float)) or not math.isfinite(value)
                                        for value in window)
                or window[0] < 0 or window[0] > window[1] for window in windows):
            raise ValueError(f'Invalid expected windows in case {row["case_id"]}')
        row['windows'] = windows
    return rows


def run_case(row, base, mode='offline'):
    config = json.loads((base / row['config']).read_text(encoding='utf-8'))
    zones = [Zone.model_validate(item) for item in config['zones']]
    rules = [Rule.model_validate(item) for item in config['rules']]
    arrivals, published = {}, {}
    def observe(tf):
        for index, (start, end) in enumerate(row['windows']):
            if tf.ts >= start and index not in arrivals:
                arrivals[index] = time.monotonic()
    def emitted(alert):
        published[alert.id] = time.monotonic()
    if mode == 'offline':
        provider = StubVerifier({
            'transparent_bag': Verdict(answer={'clear': True, 'opaque': False}.get(row['stub_bag']),
                confidence=0.9, reason='STUB eval result'),
            'professional_camera': Verdict(answer={'professional': True, 'ordinary': False}.get(row['stub_camera']),
                confidence=0.9, reason='STUB eval result'),
        })
    else:
        from verify.verifier import verify_crop
        provider = verify_crop
    started = time.monotonic()
    with VerificationScheduler(provider) as scheduler:
        if mode == 'offline':
            def timed():
                for tf in read_frames(base / row['tracks']):
                    observe(tf)
                    yield tf
            alerts = replay_clip(base / row['clip'], timed(), zones=zones, rules=rules,
                                 scheduler=scheduler, on_alert=emitted)
        else:
            camera = Camera(id=row['camera_id'], name='Evaluation', source=f'clip:{base / row["clip"]}')
            pipeline = VisionSource(camera.id, camera.source)
            engine = RuleEngine(camera.id, zones, rules, scheduler=scheduler)
            alerts = []
            try:
                from app.adapter import ContractAdapter
                adapter = ContractAdapter(camera.id)
                for image, raw in pipeline.frames():
                    tf, restarted = adapter.convert(raw)
                    if tf is None:
                        continue
                    if restarted:
                        engine.reset()
                    observe(tf)
                    new = engine.update(image, tf)[1]
                    for alert in new:
                        emitted(alert)
                    alerts.extend(new)
                for alert in engine.drain_verifications():
                    emitted(alert)
                    alerts.append(alert)
            finally:
                pipeline.stop()
    alerts = [alert for alert in alerts if row['rule'] == '*' or alert.rule_id == row['rule']]
    metrics = score(alerts, row['windows'])
    delays = [max(0, published[alert_id] - arrivals[index])
              for alert_id, index in metrics.pop('matches') if index in arrivals]
    metrics['wall_delays'] = delays
    metrics.update(case_id=row['case_id'], alerts=len(alerts), elapsed_seconds=time.monotonic() - started)
    metrics['passed'] = not any(metrics[key] for key in ['false_alerts', 'missed_events', 'duplicate_alerts'])
    return metrics


def evaluate(cases, mode='offline'):
    path = Path(cases)
    results = []
    for row in load_cases(path):
        try:
            results.append(run_case(row, path.parent, mode))
        except Exception as exc:
            results.append({'case_id': row['case_id'], 'passed': False, 'error': type(exc).__name__})
    source_delays = [value for case in results for value in case.get('source_delays', [])]
    wall_delays = [value for case in results for value in case.get('wall_delays', [])]
    report = {'mode': mode,
        'scope': ('SYNTHETIC saved-track and canned-verdict functional evaluation; no detector or Gemini accuracy'
                  if mode == 'offline' else 'Vision + rule engine + verifier; excludes HTTP/UI/evidence latency'),
        'cases': results, 'passed': sum(case['passed'] for case in results), 'total': len(results),
        'mean_source_delay_seconds': sum(source_delays) / len(source_delays) if source_delays else None,
        'mean_alert_latency_seconds': sum(wall_delays) / len(wall_delays) if wall_delays else None,
        'latency_definition': 'First processed frame at expected threshold to new alert; not capture-to-UI latency'}
    for key in ['correct_detections', 'false_alerts', 'missed_events', 'duplicate_alerts']:
        report[key] = sum(case.get(key, 0) for case in results)
    report['errors'] = sum('error' in case for case in results)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cases', type=Path, nargs='?', default=Path(__file__).with_name('recorded_cases.csv'))
    parser.add_argument('--mode', choices=['offline', 'integrated'], default='offline')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        report = evaluate(args.cases, args.mode)
    except (ValueError, OSError) as exc:
        parser.exit(2, f'Evaluation setup failed: {type(exc).__name__}\n')
    text = json.dumps(report, indent=2) + '\n'
    print(text, end='')
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
    raise SystemExit(0 if report['passed'] == report['total'] else 1)


if __name__ == '__main__':
    main()
