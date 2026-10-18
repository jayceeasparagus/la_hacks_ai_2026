"""Score the rule engine against labeled cases: correct, false, missed, duplicate alerts and latency.

Run from backend/ (so app/, engine/ and verify/ import):

    python -B -m engine.fake_tracks ../eval/generated      # synthetic tracks, regenerate any time
    python -B ../eval/run_eval.py ../eval/cases.csv

cases.csv columns:
    case             name shown in the report (rows starting with # are skipped)
    source           tracks:<path.jsonl>  approved TrackFrames, or Person 1's vision.dump output
                     clip:<path.mp4>      run Person 1's VisionPipeline on the clip (needs vision/ merged)
    config           JSON file with {"zones": [...], "rules": [...]}, or "synthetic" for the
                     engine.fake_tracks exit zone of each camera
    rule_id          only alerts for this rule are scored
    expected_alerts  how many alerts the case should produce
    window_start_s   source time when the alert first becomes due (latency is measured from here)
    window_end_s     last source time an alert still counts as correct
Paths are relative to the CSV file. Track replays have no video frames, so attribute rules
(clear bag, camera, safety gear) can only become manual-review alerts there; use clip: rows for them.
"""

import argparse
import csv
import json
from pathlib import Path
import sys
import time

BACKEND = Path(__file__).resolve().parents[1] / 'backend'
sys.path.insert(0, str(BACKEND))

from app.models import Rule, TrackFrame, Zone  # noqa: E402
from engine.engine import InlineExecutor, RuleEngine  # noqa: E402
from engine.fake_tracks import synthetic_config  # noqa: E402
from engine.replay import no_frame_verifier  # noqa: E402


def load_config(value: str, base: Path, camera_id: str):
    if value == 'synthetic':
        return synthetic_config(camera_id)
    data = json.loads((base / value).read_text(encoding='utf-8'))
    return ([Zone.model_validate(z) for z in data['zones']],
            [Rule.model_validate(r) for r in data['rules']])


def track_frames(path: Path):
    """(None, TrackFrame) pairs from approved JSONL or Person 1's draft dump format."""
    from app.adapter import ContractAdapter

    adapters = {}
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            if not line.strip():
                continue
            data = json.loads(line)
            try:
                yield None, TrackFrame.model_validate(data), False
                continue
            except ValueError:
                pass
            camera_id = data['camera_id']
            adapter = adapters.setdefault(camera_id, ContractAdapter(camera_id))
            tf, restarted = adapter.convert(data)
            if tf is not None:
                yield None, tf, restarted


def clip_frames(path: Path, camera_id: str):
    try:
        from vision.pipeline import VisionPipeline
    except ImportError as exc:
        raise SystemExit(f'clip: rows need Person 1\'s vision pipeline ({exc}); '
                         'or dump tracks first with python -m vision.dump') from exc
    from app.adapter import ContractAdapter

    adapter = ContractAdapter(camera_id)
    pipeline = VisionPipeline(camera_id, f'clip:{path}', realtime=False)
    try:
        for image, draft in pipeline.frames():
            tf, restarted = adapter.convert(draft)
            if tf is not None:
                yield image, tf, restarted
    finally:
        pipeline.stop()


def run_case(row: dict, base: Path) -> dict:
    kind, _, value = row['source'].partition(':')
    path = base / value
    camera_id = row.get('camera_id') or 'cam_exit'
    if kind == 'tracks':
        frames = list(track_frames(path))
        if frames:
            camera_id = frames[0][1].camera_id
        verifier = no_frame_verifier
    elif kind == 'clip':
        frames = clip_frames(path, camera_id)
        verifier = None  # Person 2's verify_crop; POLICYLENS_FAKE_LLM=1 keeps it offline
    else:
        raise ValueError(f'unknown source {row["source"]!r}; use tracks:<path> or clip:<path>')

    zones, rules = load_config(row['config'], base, camera_id)
    engine = RuleEngine(camera_id, zones, rules, verifier=verifier, executor=InlineExecutor(),
                        session_id=f'eval-{row["case"]}')
    alerts, started = [], time.monotonic()
    for image, tf, restarted in frames:
        if restarted and alerts:
            engine.reset()
        alerts += engine.update(image, tf)[1]
    alerts += engine.drain()
    engine.close()

    scored = [a for a in alerts if a.rule_id == row['rule_id']]
    start, end = float(row['window_start_s']), float(row['window_end_s'])
    in_window = [a for a in scored if start - 1e-9 <= a.ts <= end + 1e-9]
    expected = int(row['expected_alerts'])
    return {
        'case': row['case'],
        'expected': expected,
        'alerts': len(scored),
        'correct': min(len(in_window), expected),
        'duplicates': max(0, len(in_window) - expected),
        'false': len(scored) - len(in_window),
        'missed': max(0, expected - len(in_window)),
        'manual_review': sum(a.title == 'Manual review needed' for a in scored),
        'latency_s': (min(a.ts for a in in_window) - start) if in_window else None,
        'runtime_s': time.monotonic() - started,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('cases', type=Path)
    parser.add_argument('--json', type=Path, help='also write the results as JSON')
    args = parser.parse_args()

    with args.cases.open(newline='', encoding='utf-8') as stream:
        rows = [r for r in csv.DictReader(stream) if r['case'] and not r['case'].startswith('#')]
    results = [run_case(row, args.cases.parent) for row in rows]

    header = ('case', 'expected', 'alerts', 'correct', 'false', 'missed', 'duplicates', 'manual_review', 'latency_s')
    widths = [max(len(h), *(len(_fmt(r[h])) for r in results)) for h in header]
    print('  '.join(h.ljust(w) for h, w in zip(header, widths)))
    for r in results:
        print('  '.join(_fmt(r[h]).ljust(w) for h, w in zip(header, widths)))
    latencies = [r['latency_s'] for r in results if r['latency_s'] is not None]
    totals = {k: sum(r[k] for r in results) for k in ('expected', 'correct', 'false', 'missed', 'duplicates')}
    print(f"\n{len(results)} cases: {totals['correct']}/{totals['expected']} expected alerts correct, "
          f"{totals['false']} false, {totals['missed']} missed, {totals['duplicates']} duplicate; "
          f"mean alert latency {sum(latencies) / len(latencies):.2f} s" if latencies else
          f"\n{len(results)} cases: {totals['correct']}/{totals['expected']} expected alerts correct, "
          f"{totals['false']} false, {totals['missed']} missed, {totals['duplicates']} duplicate")
    if args.json:
        args.json.write_text(json.dumps(results, indent=2), encoding='utf-8')


def _fmt(value) -> str:
    if value is None:
        return '-'
    return f'{value:.2f}' if isinstance(value, float) else str(value)


if __name__ == '__main__':
    main()
