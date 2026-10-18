import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

import cv2
import numpy as np

from app.demo import demo_cameras, demo_rules, demo_zones
from app.events import EventHub
from app.pipelines import FakePipeline
from app.runtime import Monitor
from engine.demo_recording import write_demo
from engine.evidence import EvidenceWriter
from engine.verification import VerificationScheduler
from store.config import ConfigurationStore
from store.db import AlertStore


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError('Timed out waiting for worker result')


class RuntimeTests(unittest.TestCase):
    def configure(self, root):
        write_demo(root / 'clips')
        cameras = demo_cameras()
        cameras[0].source = f'clip:{root / "clips/entrance.mp4"}'
        cameras[1].source = f'clip:{root / "clips/exit.mp4"}'
        settings = ConfigurationStore(root / 'config.json')
        settings.replace(cameras=cameras, zones=demo_zones(), rules=[demo_rules()[2]])
        return settings

    def test_failed_camera_does_not_stop_other_camera_and_restart_is_safe(self):
        with TemporaryDirectory() as directory, VerificationScheduler() as scheduler:
            root = Path(directory)
            settings = self.configure(root)
            store = AlertStore(root / 'db')
            attempts = []
            def factory(camera):
                if camera.id == 'cam_entrance':
                    attempts.append(camera.id)
                    raise RuntimeError('rtsp://password@private-camera')
                return FakePipeline(camera, realtime=False)
            with EvidenceWriter(root / 'evidence') as writer:
                monitor = Monitor(settings, store, EventHub(), scheduler, writer, factory, retry_seconds=0.02)
                try:
                    monitor.start(); monitor.start()
                    wait_until(lambda: store.list()[1] == 1)
                    wait_until(lambda: store.list()[0][0].evidence_status == 'ready')
                    wait_until(lambda: len(attempts) >= 2)
                    self.assertNotIn('password', str(monitor.snapshot()))
                    jpeg, version = monitor.latest('cam_exit')
                    self.assertIsNotNone(cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR))
                    monitor.stop(); monitor.stop()
                    self.assertFalse(monitor.running)
                    monitor.start()
                    wait_until(lambda: store.list()[1] == 2)
                finally:
                    monitor.stop()

    def test_setup_snapshot_does_not_start_monitoring_or_create_alerts(self):
        with TemporaryDirectory() as directory, VerificationScheduler() as scheduler:
            root = Path(directory)
            settings = self.configure(root)
            store = AlertStore(root / 'db')
            with EvidenceWriter(root / 'evidence') as writer:
                monitor = Monitor(settings, store, EventHub(), scheduler, writer,
                                  lambda camera: FakePipeline(camera, realtime=False))
                image = monitor.preview(settings.snapshot().cameras[0])
                self.assertTrue(image.startswith(b'\xff\xd8'))
                self.assertFalse(monitor.running)
                self.assertEqual(store.list()[1], 0)


class HubTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_client_receives_overflow_instead_of_blocking_producer(self):
        hub = EventHub(capacity=1)
        client = hub.subscribe()
        hub.publish('state', {})
        hub.publish('alert', {})
        await asyncio.sleep(0.01)
        self.assertEqual((await client.queue.get())['type'], '__overflow__')
        hub.unsubscribe(client)

    async def test_message_envelope(self):
        hub = EventHub()
        client = hub.subscribe()
        hub.publish('monitor_status', {'running': True})
        self.assertEqual(await client.queue.get(), {'type': 'monitor_status', 'data': {'running': True}})
        hub.unsubscribe(client)
