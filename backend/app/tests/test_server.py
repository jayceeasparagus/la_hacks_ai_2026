"""HTTP + WebSocket server end to end, with synthetic cameras and the offline fake LLM."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest import mock

os.environ['POLICYLENS_FAKE_LLM'] = '1'
os.environ.setdefault('POLICYLENS_SOURCE_SPEED', '10')

from fastapi.testclient import TestClient  # noqa: E402

from app.demo import demo_cameras, demo_rules, demo_zones  # noqa: E402
from app.main import create_app  # noqa: E402
from app.settings import Settings  # noqa: E402
from engine.fake_tracks import scenario  # noqa: E402

DEMO_PROMPT = ('At the main entrance, only clear bags are permitted and professional cameras '
               'require review. Keep the emergency exit clear; alert if a bag or chair blocks it '
               'for more than five seconds.')
SYNTHETIC = {'cam_entrance': 'synthetic:entrance_bag', 'cam_exit': 'synthetic:exit_bag'}


def dump(items):
    return [item.model_dump(mode='json') for item in items]


def synthetic_cameras():
    return [camera.model_copy(update={'source': SYNTHETIC[camera.id]}) for camera in demo_cameras()]


def wait_for(check, timeout=20.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(interval)
    raise AssertionError('condition not met in time')


class ServerTestCase(unittest.TestCase):
    cameras = None  # None: no saved configuration

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        if self.cameras is not None:
            settings = Settings(self.root / 'settings')
            settings.save_cameras(self.cameras())
            settings.save_zones(demo_zones())
            settings.save_rules(demo_rules())
        self.client = TestClient(create_app(self.root))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    @property
    def manager(self):
        return self.client.app.state.manager

    def start(self):
        response = self.client.post('/api/monitor/start')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'running': True})

    def alerts(self, **params):
        response = self.client.get('/api/alerts', params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def wait_alert(self, rule_id, **params):
        return wait_for(lambda: next((alert for alert in self.alerts(**params)['alerts']
                                      if alert['rule_id'] == rule_id), None))


class ConfigurationTests(ServerTestCase):
    def test_health(self):
        response = self.client.get('/api/health')
        self.assertEqual((response.status_code, response.json()), (200, {'status': 'ok'}))

    def test_camera_zone_policy_crud(self):
        c = self.client
        self.assertEqual(c.get('/api/cameras').json(), {'cameras': []})
        self.assertEqual(c.get('/api/zones').json(), {'zones': []})
        self.assertEqual(c.get('/api/policy').json(), {'rules': []})

        cameras = {'cameras': dump(synthetic_cameras())}
        self.assertEqual(c.put('/api/cameras', json=cameras).json(), cameras)
        self.assertEqual(c.get('/api/cameras').json(), cameras)
        # Unknown fields and invalid values are 422; nothing changes.
        self.assertEqual(c.put('/api/cameras', json={**cameras, 'extra': 1}).status_code, 422)
        bad = {'cameras': [{**cameras['cameras'][0], 'url': 'x'}]}
        self.assertEqual(c.put('/api/cameras', json=bad).status_code, 422)
        self.assertEqual(c.put('/api/cameras', json=dump(synthetic_cameras())).status_code, 422)
        four = {'cameras': [{'id': f'cam_{i}', 'name': 'Cam', 'source': 'synthetic:empty'}
                            for i in range(4)]}
        self.assertEqual(c.put('/api/cameras', json=four).status_code, 422)
        twice = {'cameras': [cameras['cameras'][0], cameras['cameras'][0]]}
        self.assertEqual(c.put('/api/cameras', json=twice).status_code, 409)
        self.assertEqual(c.get('/api/cameras').json(), cameras)

        zones = {'zones': dump(demo_zones())}
        stray = {'zones': [{**zones['zones'][0], 'camera_id': 'cam_missing'}]}
        self.assertEqual(c.put('/api/zones', json=stray).status_code, 409)
        bowtie = {'zones': [{**zones['zones'][0], 'polygon': [[0, 0], [1, 1], [1, 0], [0, 1]]}]}
        self.assertEqual(c.put('/api/zones', json=bowtie).status_code, 422)
        outside = {'zones': [{**zones['zones'][0], 'polygon': [[0, 0], [1.5, 0], [1, 1]]}]}
        self.assertEqual(c.put('/api/zones', json=outside).status_code, 422)
        self.assertEqual(c.put('/api/zones', json=zones).json(), zones)

        rules = {'rules': dump(demo_rules())}
        orphan = {'rules': [{**rules['rules'][0], 'zone': 'nowhere'}]}
        self.assertEqual(c.put('/api/policy', json=orphan).status_code, 409)
        extra = {'rules': [{**rules['rules'][0], 'color': 'red'}]}
        self.assertEqual(c.put('/api/policy', json=extra).status_code, 422)
        self.assertEqual(c.put('/api/policy', json=rules).json(), rules)
        self.assertEqual(c.get('/api/policy').json(), rules)

        # Removing a camera that zones still reference is a conflict.
        self.assertEqual(c.put('/api/cameras', json={'cameras': cameras['cameras'][:1]}).status_code, 409)

        # Camera and zone changes while monitoring are conflicts; rules swap in live (still validated).
        self.start()
        for path, body in [('/api/cameras', cameras), ('/api/zones', zones)]:
            with self.subTest(path=path):
                self.assertEqual(c.put(path, json=body).status_code, 409)
        self.assertEqual(c.put('/api/policy', json=orphan).status_code, 409)
        self.assertEqual(c.put('/api/policy', json=rules).status_code, 200)
        c.post('/api/monitor/stop')
        self.assertEqual(c.put('/api/policy', json=rules).status_code, 200)

    def test_compile_uses_saved_zones_and_does_not_activate(self):
        c = self.client
        c.put('/api/cameras', json={'cameras': dump(synthetic_cameras())})
        c.put('/api/zones', json={'zones': dump(demo_zones())})
        response = c.post('/api/policy/compile', json={'prompt': DEMO_PROMPT})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(set(body), {'rules', 'warnings', 'unsupported'})
        self.assertEqual(body['rules'], dump(demo_rules()))
        self.assertEqual(c.get('/api/policy').json(), {'rules': []})
        self.assertEqual(c.post('/api/policy/compile', json={'text': DEMO_PROMPT}).status_code, 422)

    def test_monitor_start_stop_idempotent(self):
        c = self.client
        self.assertEqual(c.get('/api/monitor').json(), {'running': False, 'cameras': []})
        self.start()
        self.start()
        self.assertTrue(c.get('/api/monitor').json()['running'])
        for _ in range(2):
            response = c.post('/api/monitor/stop')
            self.assertEqual((response.status_code, response.json()), (200, {'running': False}))
        self.assertFalse(c.get('/api/monitor').json()['running'])

    def test_unknown_resources(self):
        c = self.client
        self.assertEqual(c.get('/api/alerts/nope').status_code, 404)
        self.assertEqual(c.post('/api/alerts/nope/decision', json={'decision': 'confirmed'}).status_code, 404)
        self.assertEqual(c.get('/evidence/..%2Fsettings%2Fcameras.json').status_code, 404)
        self.assertEqual(c.get('/evidence/missing.jpg').status_code, 404)
        self.assertEqual(c.get('/api/snapshot/cam_missing').status_code, 404)
        self.assertEqual(c.get('/api/stream/cam_missing').status_code, 404)
        self.assertEqual(c.get('/api/alerts', params={'status': 'closed'}).status_code, 422)
        self.assertEqual(c.get('/api/alerts', params={'limit': 0}).status_code, 422)


class SyntheticDemoTests(ServerTestCase):
    cameras = staticmethod(synthetic_cameras)

    def test_alerts_evidence_and_decisions(self):
        c = self.client
        self.start()
        exit_alert = self.wait_alert('blocked_exit')
        bag_alert = self.wait_alert('clear_bag')
        self.assertEqual(exit_alert['camera_id'], 'cam_exit')
        self.assertEqual(exit_alert['severity'], 'urgent')
        self.assertEqual(exit_alert['title'], 'Possible exit obstruction')
        self.assertEqual(bag_alert['camera_id'], 'cam_entrance')
        self.assertIn(bag_alert['title'], ('Possible non-clear bag', 'Manual review needed'))

        everything = self.alerts()
        self.assertGreaterEqual(everything['total'], 2)
        exit_only = self.alerts(camera_id='cam_exit')
        self.assertTrue(exit_only['alerts'])
        self.assertTrue(all(alert['camera_id'] == 'cam_exit' for alert in exit_only['alerts']))
        page = self.alerts(limit=1)
        self.assertEqual(len(page['alerts']), 1)
        self.assertGreaterEqual(page['total'], 2)

        # Evidence completes and is served.
        ready = wait_for(lambda: (lambda a: a if a['evidence_status'] == 'ready' else None)(
            c.get(f'/api/alerts/{exit_alert["id"]}').json()))
        image = c.get(ready['evidence_image_url'])
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.headers['content-type'], 'image/jpeg')
        self.assertTrue(image.content.startswith(b'\xff\xd8'))
        if ready['evidence_clip_url']:
            self.assertEqual(c.get(ready['evidence_clip_url']).status_code, 200)

        # Decisions mark the alert reviewed; repeating one is idempotent.
        url = f'/api/alerts/{exit_alert["id"]}/decision'
        self.assertEqual(c.post(url, json={'decision': 'maybe'}).status_code, 422)
        self.assertEqual(c.post(url, json={'decision': 'confirmed', 'x': 1}).status_code, 422)
        first = c.post(url, json={'decision': 'confirmed'}).json()
        self.assertEqual((first['status'], first['decision']), ('reviewed', 'confirmed'))
        again = c.post(url, json={'decision': 'confirmed'}).json()
        self.assertEqual(again, first)
        self.assertEqual(c.app.state.store.decisions(exit_alert['id'])[0]['decision'], 'confirmed')
        reviewed = self.alerts(status='reviewed')
        self.assertEqual([alert['id'] for alert in reviewed['alerts']], [exit_alert['id']])
        self.assertEqual(reviewed['total'], 1)

    def test_policy_swaps_into_running_cameras(self):
        c = self.client
        self.start()
        worker = wait_for(lambda: (lambda w: w if w is not None and w.source is not None else None)(
            self.manager.worker('cam_exit')))
        source = worker.source
        exit_only = [rule for rule in dump(demo_rules()) if rule['id'] == 'blocked_exit']
        response = c.put('/api/policy', json={'rules': exit_only})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(c.get('/api/policy').json(), {'rules': exit_only})
        self.assertEqual([rule.id for rule in worker.engine.rules], ['blocked_exit'])
        self.assertEqual(self.manager.worker('cam_entrance').engine.rules, [])
        self.assertIs(worker.source, source)  # the camera kept playing; nothing restarted
        self.assertTrue(c.get('/api/monitor').json()['running'])
        self.wait_alert('blocked_exit')
        self.assertEqual(c.put('/api/policy', json={'rules': []}).status_code, 200)
        self.assertEqual(worker.engine.rules, [])

    def test_websocket_snapshot_then_alert(self):
        with self.client.websocket_connect('/ws') as ws:
            first = ws.receive_json()
            self.assertEqual(first['type'], 'snapshot')
            self.assertEqual(set(first['data']), {'running', 'cameras', 'rule_states'})
            self.assertFalse(first['data']['running'])
            self.start()
            seen = set()
            for _ in range(5000):
                message = ws.receive_json()
                self.assertEqual(set(message), {'type', 'data'})
                seen.add(message['type'])
                if message['type'] == 'state':
                    self.assertEqual(set(message['data']), {'camera_id', 'ts', 'rule_states'})
                if message['type'] == 'alert':
                    self.assertIn(message['data']['camera_id'], SYNTHETIC)
                    break
            self.assertIn('alert', seen)
            self.assertIn('monitor_status', seen)

    def test_stream_and_snapshots(self):
        c = self.client
        self.assertEqual(c.get('/api/stream/cam_exit').status_code, 503)  # not monitoring
        idle = c.get('/api/snapshot/cam_exit')  # synthetic sources render their first frame
        self.assertEqual((idle.status_code, idle.headers['content-type']), (200, 'image/jpeg'))
        self.start()
        wait_for(lambda: c.get('/api/snapshot/cam_exit').status_code == 200)
        threading.Timer(1.0, self.manager.stop).start()  # ends the otherwise endless stream
        response = c.get('/api/stream/cam_exit')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers['content-type'].startswith('multipart/x-mixed-replace'))
        self.assertIn(b'--frame\r\nContent-Type: image/jpeg', response.content)

    def test_bad_camera_stays_offline_while_other_works(self):
        c = self.client
        cameras = synthetic_cameras()[1:] + [
            demo_cameras()[0].model_copy(update={'id': 'cam_bad', 'source': 'bogus:1'})]
        c.put('/api/policy', json={'rules': []})
        c.put('/api/zones', json={'zones': dump(demo_zones()[1:])})
        c.put('/api/cameras', json={'cameras': dump(cameras)})
        c.put('/api/policy', json={'rules': dump(demo_rules()[2:])})
        self.start()
        self.wait_alert('blocked_exit')
        statuses = {s['camera_id']: s for s in c.get('/api/monitor').json()['cameras']}
        self.assertEqual(statuses['cam_bad']['status'], 'offline')
        self.assertIn('unsupported camera source', statuses['cam_bad']['error'])
        self.assertEqual(statuses['cam_exit']['status'], 'online')
        self.assertIsNone(statuses['cam_exit']['error'])
        self.assertEqual(c.get('/api/snapshot/cam_bad').status_code, 503)
        self.assertEqual(c.get('/api/snapshot/cam_exit').status_code, 200)


class SeedTests(unittest.TestCase):
    def test_env_seeds_synthetic_demo(self):
        with TemporaryDirectory() as temp, mock.patch.dict(os.environ, {
                'POLICYLENS_SEED_DEMO': '1', 'POLICYLENS_DEMO_SOURCES': 'synthetic'}):
            with TestClient(create_app(Path(temp))) as client:
                cameras = client.get('/api/cameras').json()['cameras']
                self.assertEqual({c['id']: c['source'] for c in cameras}, SYNTHETIC)
                self.assertEqual(len(client.get('/api/policy').json()['rules']), 3)
                self.assertEqual(len(client.get('/api/zones').json()['zones']), 2)


class ReplayTests(ServerTestCase):
    def test_replay_source_alerts_then_ends(self):
        path = self.root / 'exit_bag.tracks.jsonl'
        path.write_text(''.join(tf.model_dump_json() + '\n' for tf in scenario('exit_bag')),
                        encoding='utf-8')
        c = self.client
        cameras = [demo_cameras()[1].model_copy(update={'source': f'replay:{path}'})]
        c.put('/api/cameras', json={'cameras': dump(cameras)})
        c.put('/api/zones', json={'zones': dump(demo_zones()[1:])})
        c.put('/api/policy', json={'rules': dump(demo_rules()[2:])})
        self.start()
        self.wait_alert('blocked_exit')
        ended = wait_for(lambda: next((s for s in c.get('/api/monitor').json()['cameras']
                                       if s['error'] == 'replay ended'), None))
        self.assertEqual(ended['status'], 'offline')
        self.assertEqual(self.alerts()['total'], 1)


class LoopTests(ServerTestCase):
    def test_looping_source_alerts_once_per_track(self):
        path = self.root / 'exit_bag.tracks.jsonl'
        frames = scenario('exit_bag')
        path.write_text(''.join(tf.model_dump_json() + '\n' for tf in frames), encoding='utf-8')
        c = self.client
        cameras = [demo_cameras()[1].model_copy(update={'source': f'loop:{path}'})]
        c.put('/api/cameras', json={'cameras': dump(cameras)})
        c.put('/api/zones', json={'zones': dump(demo_zones()[1:])})
        c.put('/api/policy', json={'rules': dump(demo_rules()[2:])})
        self.start()
        worker = self.manager.worker('cam_exit')
        wait_for(lambda: worker.frames_processed > 3 * len(frames), timeout=60)  # three loops
        self.assertEqual(self.alerts()['total'], 1)
        status = c.get('/api/monitor').json()['cameras'][0]
        self.assertEqual(status['status'], 'online')  # still playing
        # A new policy starts a fresh session: the same track may alert once more.
        c.put('/api/policy', json={'rules': dump(demo_rules()[2:])})
        wait_for(lambda: self.alerts()['total'] == 2, timeout=60)


class VisionSourceTests(unittest.TestCase):
    def test_missing_vision_pipeline_is_reported(self):
        from app.sources import VISION_MISSING, SourceError, VisionSource
        source = VisionSource('cam_a', 'webcam:0')
        with mock.patch.dict('sys.modules', {'vision.pipeline': None}):
            with self.assertRaises(SourceError):
                next(iter(source.frames()))
        self.assertEqual((source.status, source.error), ('offline', VISION_MISSING))


if __name__ == '__main__':
    unittest.main()
