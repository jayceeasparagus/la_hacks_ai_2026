"""Regressions for improvements ported onto main's server interfaces."""
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

from app.demo import demo_rules, demo_zones
from app.evidence import EvidenceWriter
from app.main import create_app
from app.models import Camera, Track, TrackFrame, Verdict
from app.workers import CameraWorker
from engine.verification import VerificationScheduler
from store.db import AlertStore


def wait_for(check):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(.01)
    raise AssertionError('background result did not arrive')


class IntegrationImprovementTests(unittest.TestCase):
    def test_idle_verification_and_disconnect_session(self):
        release = threading.Event()
        def provider(image, check):
            release.wait(2)
            return Verdict(answer=False, confidence=.9, reason='test opaque bag')
        with TemporaryDirectory() as directory, VerificationScheduler(provider) as scheduler:
            root = Path(directory)
            store, evidence = AlertStore(root / 'alerts.db'), EvidenceWriter(root / 'evidence')
            events = []
            worker = CameraWorker(Camera(id='cam_entrance', name='Entrance', source='synthetic:empty'),
                demo_zones(), [demo_rules()[0]], source_factory=None, store=store,
                evidence=evidence, publish=lambda kind, value: events.append((kind, value)),
                scheduler=scheduler)
            image = np.full((120, 160, 3), 100, np.uint8)
            def feed(start):
                for tick in range(12):
                    worker._process(image, TrackFrame(camera_id='cam_entrance', ts=start+tick/10,
                        tracks=[Track(track_id=1, object_class='backpack', bbox=(.3,.3,.5,.7), confidence=.9)]))
            try:
                feed(0)
                self.assertEqual(store.list()[1], 0)
                worker.poll_pending({'status': 'offline'})
                release.set()
                worker.poll_pending({'status': 'online'})
                self.assertEqual(store.list()[1], 0)  # old session cannot alert after reconnect
                feed(100)  # same track ID, new source clock, new verification
                def poll():
                    worker.poll_pending({'status': 'online'})
                    return store.list()[1] == 1
                wait_for(poll)  # no further camera frame is needed
                alert = store.list()[0][0]
                self.assertAlmostEqual(alert.ts, 1)
                self.assertEqual(sum(kind == 'alert' for kind, _ in events), 1)
            finally:
                release.set()
                worker.close()
                evidence.shutdown()
                store.close()

    def test_monitor_restarts_reuse_verifier_capacity(self):
        with TemporaryDirectory() as directory, TestClient(create_app(Path(directory))) as client:
            self.assertEqual(client.post('/api/monitor/start').status_code, 200)
            scheduler = client.app.state.manager.scheduler
            client.post('/api/monitor/stop')
            self.assertEqual(client.post('/api/monitor/start').status_code, 200)
            self.assertIs(client.app.state.manager.scheduler, scheduler)

    def test_evidence_queue_is_bounded(self):
        from engine.fake_tracks import scenario, synthetic_config
        from engine.engine import RuleEngine
        zones, rules = synthetic_config()
        engine = RuleEngine('cam_exit', zones, rules)
        alert = [a for tf in scenario('exit_bag') for a in engine.update(None, tf)[1]][0]
        release = threading.Event()
        with TemporaryDirectory() as directory:
            writer = EvidenceWriter(Path(directory), max_workers=1, max_pending=1)
            try:
                with patch.object(writer, '_work', side_effect=lambda *args: release.wait(2)):
                    image = np.zeros((120,160,3), np.uint8)
                    self.assertEqual(writer.submit(alert, image, [], lambda a: None).evidence_status, 'pending')
                    started = time.monotonic()
                    self.assertEqual(writer.submit(alert, image, [], lambda a: None).evidence_status, 'unavailable')
                    self.assertLess(time.monotonic() - started, .1)
            finally:
                release.set()
                writer.shutdown()
                engine.close()

    def test_late_evidence_changes_only_evidence_fields(self):
        from engine.fake_tracks import scenario, synthetic_config
        from engine.engine import RuleEngine
        zones, rules = synthetic_config()
        engine = RuleEngine('cam_exit', zones, rules)
        alert = [a for tf in scenario('exit_bag') for a in engine.update(None, tf)[1]][0]
        store = AlertStore(':memory:')
        try:
            store.add(alert)
            reviewed = store.decide(alert.id, 'confirmed', '2026-10-18T00:00:00Z')
            stale = alert.model_copy(update={'title': 'stale title', 'evidence_status': 'ready',
                                             'evidence_image_url': '/evidence/test.jpg'})
            updated = store.update(stale)
            self.assertEqual(updated.title, alert.title)
            self.assertEqual(updated.decision, reviewed.decision)
            self.assertEqual(updated.evidence_status, 'ready')
        finally:
            store.close()
            engine.close()


class EvidenceRangeTests(unittest.TestCase):
    def test_evidence_supports_partial_content(self):
        import cv2
        with TemporaryDirectory() as directory, TestClient(create_app(Path(directory))) as client:
            ok, encoded = cv2.imencode('.jpg', np.zeros((120,160,3), np.uint8))
            self.assertTrue(ok)
            (client.app.state.evidence.directory / 'range.jpg').write_bytes(encoded.tobytes())
            response = client.get('/evidence/range.jpg', headers={'Range': 'bytes=0-9'})
            self.assertEqual(response.status_code, 206)
            self.assertEqual(response.content, encoded.tobytes()[:10])


class SlowClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_alert_overflow_requires_reloading_instead_of_silent_loss(self):
        from app.broadcast import _Client
        client = _Client(None, 2)
        client.put('alert', 'first')
        client.put('alert_updated', 'second')
        client.put('alert', 'third')
        self.assertTrue(client.overflow)
        self.assertEqual(len(client.queue), 2)

    async def test_transient_state_can_be_discarded_before_an_alert(self):
        from app.broadcast import _Client
        client = _Client(None, 2)
        client.put('state', 'old state')
        client.put('alert', 'first')
        client.put('alert', 'second')
        self.assertFalse(client.overflow)
        self.assertEqual([kind for kind, _ in client.queue], ['alert', 'alert'])
