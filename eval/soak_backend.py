"""Continuous two-camera HTTP/WebSocket check using explicitly synthetic inputs."""

import argparse
import json
import logging
from pathlib import Path
import resource
import sys
import threading
import time
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'backend'))

import numpy as np
from fastapi.testclient import TestClient
from app.main import create_app
from app.demo import demo_cameras, demo_rules, demo_zones
from app.models import Track, TrackFrame


class SoakPipeline:
    """New synthetic objects every 20 s, with 8 s in-zone presence at 10 Hz."""
    def __init__(self, camera):
        self.camera = camera
        self.status = 'connecting'
        self.closed = threading.Event()

    def frames(self):
        began = time.monotonic()
        while not self.closed.is_set():
            ts = time.monotonic() - began
            cycle = int(ts // 20)
            tracks = []
            if ts % 20 < 8:
                tracks.append(Track(track_id=cycle * 2 + 1, object_class='backpack',
                    bbox=(0.3, 0.3, 0.5, 0.7), confidence=0.95))
                if self.camera.id == 'cam_entrance':
                    tracks.append(Track(track_id=cycle * 2 + 2, object_class='camera',
                        bbox=(0.55, 0.3, 0.75, 0.7), confidence=0.9))
            self.status = 'online'
            yield np.full((270, 480, 3), 100, np.uint8), TrackFrame(
                camera_id=self.camera.id, ts=ts, tracks=tracks)
            self.closed.wait(0.1)

    def stop(self):
        self.closed.set()


def run(seconds=300, output=None):
    if seconds < 20 or seconds % 20:
        raise ValueError('Duration must be a positive multiple of 20 seconds')
    root = REPO / 'eval/generated/soak' / uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    output = Path(output or root / 'report.json')
    expected = 3 * (seconds // 20)
    app = create_app(data_dir=root / 'data', mode='demo', pipeline_factory=SoakPipeline)
    report = {'mode': 'Synthetic two-camera backend; stub verifier; TestClient HTTP + WebSocket',
              'target_seconds': seconds, 'expected_alerts': expected, 'passed': False}
    started = time.monotonic()
    try:
        with TestClient(app) as client:
            cameras = demo_cameras()
            for camera in cameras:
                camera.source = 'clip:synthetic-soak'
            for endpoint, payload in [('/api/cameras', {'cameras': [c.model_dump() for c in cameras]}),
                ('/api/zones', {'zones': [z.model_dump() for z in demo_zones()]}),
                ('/api/policy', {'rules': [r.model_dump() for r in demo_rules()]})]:
                assert client.put(endpoint, json=payload).status_code == 200
            with client.websocket_connect('/ws') as socket:
                assert socket.receive_json()['type'] == 'snapshot'
                assert client.post('/api/monitor/start').status_code == 200
                started, next_check, messages = time.monotonic(), 0, 0
                alert_ids, threads = set(), []
                while time.monotonic() - started < seconds:
                    message = socket.receive_json()
                    messages += 1
                    if message['type'] == 'alert':
                        alert = message['data']
                        assert alert['id'] not in alert_ids
                        alert_ids.add(alert['id'])
                        assert client.post(f'/api/alerts/{alert["id"]}/decision',
                                           json={'decision': 'unclear'}).status_code == 200
                    elapsed = time.monotonic() - started
                    if elapsed >= next_check:
                        assert client.get('/api/health').json() == {'status': 'ok'}
                        assert client.get('/api/monitor').json()['running']
                        threads.append(threading.active_count())
                        print(f'{elapsed:.1f}s messages={messages} alerts={len(alert_ids)} threads={threads[-1]}', flush=True)
                        next_check = elapsed + 30
                assert client.post('/api/monitor/stop').json() == {'running': False}
                result = client.get('/api/alerts?limit=500').json()
                rows = result['alerts']
                assert result['total'] == expected
                assert len({alert['incident_id'] for alert in rows}) == expected
                assert all(alert['decision'] == 'unclear' for alert in rows)
                assert all(alert['evidence_status'] == 'ready' for alert in rows)
                report.update(passed=True, elapsed_seconds=time.monotonic() - started,
                    messages=messages, alerts=result['total'], reviewed=len(rows),
                    evidence_ready=sum(alert['evidence_status'] == 'ready' for alert in rows),
                    min_threads=min(threads), max_threads=max(threads),
                    max_rss_raw=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except Exception as exc:
        report.update(error=type(exc).__name__, elapsed_seconds=time.monotonic() - started)
        raise
    finally:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, indent=2), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=300)
    parser.add_argument('--output', type=Path, default=REPO / 'eval/generated/soak-report.json')
    args = parser.parse_args()
    logging.basicConfig(level=logging.ERROR)
    run(args.seconds, args.output)
