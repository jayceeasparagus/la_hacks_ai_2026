from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient

from app.demo import demo_cameras, demo_rules, demo_zones
from app.main import create_app
from app.models import Verdict
from app.tests.test_runtime import wait_until
from engine.demo_recording import write_demo
from engine.verification import StubVerifier


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        write_demo(self.root / 'clips')
        self.verifier = StubVerifier({
            'transparent_bag': Verdict(answer=True, confidence=0.9, reason='STUB'),
            'professional_camera': Verdict(answer=False, confidence=0.9, reason='STUB'),
        })
        self.app = create_app(data_dir=self.root / 'data', verifier=self.verifier, realtime=False)
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temporary.cleanup()

    def configure(self):
        cameras = demo_cameras()
        cameras[0].source = f'clip:{self.root / "clips/entrance.mp4"}'
        cameras[1].source = f'clip:{self.root / "clips/exit.mp4"}'
        self.assertEqual(self.client.put('/api/cameras', json={'cameras': [c.model_dump() for c in cameras]}).status_code, 200)
        self.assertEqual(self.client.put('/api/zones', json={'zones': [z.model_dump() for z in demo_zones()]}).status_code, 200)
        self.assertEqual(self.client.put('/api/policy', json={'rules': [r.model_dump() for r in demo_rules()]}).status_code, 200)

    def test_all_configuration_routes_and_compile_do_not_activate(self):
        self.configure()
        self.assertEqual(self.client.get('/api/health').json(), {'status': 'ok'})
        self.assertEqual(len(self.client.get('/api/cameras').json()['cameras']), 2)
        self.assertEqual(len(self.client.get('/api/zones').json()['zones']), 2)
        before = self.client.get('/api/policy').json()
        compiled = self.client.post('/api/policy/compile', json={'prompt':
            'At the main entrance only clear bags are allowed. Professional cameras require review. Keep the emergency exit clear.'})
        self.assertEqual(compiled.status_code, 200)
        self.assertEqual(len(compiled.json()['rules']), 3)
        self.assertIn('DEMO', compiled.json()['warnings'][0])
        self.assertEqual(self.client.get('/api/policy').json(), before)

    def test_validation_duplicate_references_limits_and_unknown_fields(self):
        self.configure()
        camera = demo_cameras()[0].model_dump()
        self.assertEqual(self.client.put('/api/cameras', json={'cameras': [camera, camera]}).status_code, 409)
        self.assertEqual(self.client.put('/api/cameras', json={'cameras': []}).status_code, 422)
        self.assertEqual(self.client.put('/api/cameras', json={'cameras': [], 'unknown': True}).status_code, 422)
        self.assertEqual(self.client.post('/api/monitor/start', json={'unknown': True}).status_code, 422)
        self.assertEqual(self.client.get('/api/alerts?limit=0').status_code, 422)
        self.assertEqual(self.client.get('/api/alerts?status=invalid').status_code, 422)
        zone = demo_zones()[0].model_dump()
        zone['polygon'] = [[0,0], [1,1], [1,0], [0,1]]
        self.assertEqual(self.client.put('/api/zones', json={'zones': [zone]}).status_code, 422)

    def test_snapshot_before_start_and_unavailable_stream(self):
        self.configure()
        image = self.client.get('/api/snapshot/cam_exit')
        self.assertEqual(image.status_code, 200)
        self.assertTrue(image.content.startswith(b'\xff\xd8'))
        self.assertFalse(self.client.get('/api/monitor').json()['running'])
        self.assertEqual(self.client.get('/api/snapshot/missing').status_code, 404)
        self.assertEqual(self.client.get('/api/stream/missing').status_code, 404)

    def test_monitor_alert_decision_evidence_and_range_requests(self):
        self.configure()
        self.assertEqual(self.client.post('/api/monitor/start').json(), {'running': True})
        self.assertEqual(self.client.post('/api/monitor/start').status_code, 200)
        self.assertEqual(self.client.put('/api/policy', json={'rules': []}).status_code, 409)
        wait_until(lambda: self.client.get('/api/alerts').json()['total'] == 1)
        wait_until(lambda: self.client.get('/api/alerts').json()['alerts'][0]['evidence_status'] == 'ready')
        alert = self.client.get('/api/alerts?camera_id=cam_exit').json()['alerts'][0]
        self.assertEqual(self.client.get('/api/alerts?camera_id=cam_entrance').json()['total'], 0)
        self.assertEqual(self.client.get(f'/api/alerts/{alert["id"]}').status_code, 200)
        reviewed = self.client.post(f'/api/alerts/{alert["id"]}/decision', json={'decision': 'dismissed'})
        self.assertEqual(reviewed.json()['status'], 'reviewed')
        self.assertEqual(self.client.get('/api/alerts?status=reviewed').json()['total'], 1)
        self.assertEqual(self.client.get(alert['evidence_image_url']).headers['content-type'], 'image/jpeg')
        video = self.client.get(alert['evidence_clip_url'], headers={'Range': 'bytes=0-15'})
        self.assertEqual(video.status_code, 206)
        self.assertEqual(len(video.content), 16)
        self.assertEqual(self.client.get('/evidence/config.json').status_code, 404)
        self.assertEqual(self.client.post('/api/monitor/stop').json(), {'running': False})
        self.assertEqual(self.client.post('/api/monitor/stop').status_code, 200)

    def test_websocket_snapshot_alert_and_evidence_update(self):
        self.configure()
        with self.client.websocket_connect('/ws') as socket:
            initial = socket.receive_json()
            self.assertEqual(initial['type'], 'snapshot')
            self.assertEqual(len(initial['data']['cameras']), 2)
            self.client.post('/api/monitor/start')
            seen = set()
            for _ in range(100):
                message = socket.receive_json()
                seen.add(message['type'])
                if message['type'] == 'alert_updated' and message['data']['evidence_status'] == 'ready':
                    break
            self.assertTrue({'alert', 'alert_updated'}.issubset(seen))

    def test_state_persists_across_app_restart(self):
        self.configure()
        self.client.post('/api/monitor/start')
        wait_until(lambda: self.client.get('/api/alerts').json()['total'] == 1)
        self.client.post('/api/monitor/stop')
        with TestClient(create_app(data_dir=self.root / 'data')) as restarted:
            self.assertEqual(len(restarted.get('/api/cameras').json()['cameras']), 2)
            self.assertEqual(restarted.get('/api/alerts').json()['total'], 1)
            self.assertFalse(restarted.get('/api/monitor').json()['running'])

    def test_unknown_alerts_and_unsupported_policy(self):
        self.assertEqual(self.client.get('/api/alerts/missing').status_code, 404)
        self.assertEqual(self.client.post('/api/alerts/missing/decision', json={'decision': 'confirmed'}).status_code, 404)
        response = self.client.post('/api/policy/compile', json={'prompt': 'Detect concealed items'})
        self.assertTrue(response.json()['unsupported'])
        self.assertEqual(self.client.post('/api/monitor/start').status_code, 422)
