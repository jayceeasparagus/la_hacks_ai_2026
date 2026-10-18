from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from app.demo import demo_rules, demo_zones
from app.models import Track, TrackFrame, Verdict
from engine.clip_replay import replay_clip
from engine.engine import RuleEngine
from engine.evidence import EvidenceWriter
from engine.fake_tracks import scenario, synthetic_config
from engine.verification import StubVerifier, VerificationScheduler


class EvidenceIntegrationTests(unittest.TestCase):
    def test_temporal_alert_publishes_before_encoding_finishes(self):
        release = threading.Event()
        with TemporaryDirectory() as directory, EvidenceWriter(Path(directory)) as writer:
            actual = writer._write
            def slow(*args):
                release.wait(2)
                return actual(*args)
            with patch.object(writer, '_write', side_effect=slow):
                zones, rules = synthetic_config()
                engine = RuleEngine('cam_exit', zones, rules, evidence_writer=writer)
                image = np.full((120, 160, 3), 150, np.uint8)
                alerts = []
                for tf in scenario('exit_bag')[:51]:
                    started = time.monotonic()
                    alerts.extend(engine.update(image, tf)[1])
                    self.assertLess(time.monotonic() - started, 0.1)
                self.assertEqual(len(alerts), 1)
                self.assertEqual(alerts[0].evidence_status, 'pending')
                self.assertIsNone(alerts[0].evidence_image_url)
                self.assertEqual(engine.poll_evidence(), [])
                release.set()
                updates = engine.drain_evidence()
                self.assertEqual(len(updates), 1)
                updated = updates[0].apply(alerts[0])
                self.assertEqual(updated.id, alerts[0].id)
                self.assertEqual(updated.evidence_status, 'ready')
                self.assertEqual(engine.poll_evidence(), [])

    def test_slow_attribute_check_keeps_original_snapshot_and_clip_window(self):
        release = threading.Event()
        def provider(crop, check):
            release.wait(2)
            return Verdict(answer=False, confidence=0.9, reason='test opaque')
        with TemporaryDirectory() as directory, VerificationScheduler(provider) as scheduler, EvidenceWriter(Path(directory)) as writer:
            rule = demo_rules()[0].model_copy(update={'duration_seconds': 5})
            engine = RuleEngine('cam_entrance', demo_zones(), [rule], scheduler=scheduler,
                                evidence_writer=writer)
            for tick in range(81):
                frame = np.full((120, 160, 3), 190 if tick == 0 else 10, np.uint8)
                tf = TrackFrame(camera_id='cam_entrance', ts=tick / 10, tracks=[
                    Track(track_id=1, object_class='backpack', bbox=(0.3, 0.3, 0.5, 0.7), confidence=0.9)])
                engine.update(frame, tf)
            release.set()
            alerts = engine.drain_verifications()
            self.assertEqual(len(alerts), 1)
            self.assertEqual(alerts[0].ts, 5)
            updates = engine.drain_evidence()
            updated = updates[0].apply(alerts[0])
            image = cv2.imread(str(Path(directory) / Path(updated.evidence_image_url).name))
            self.assertGreater(image[80:110, 100:150].mean(), 170)
            capture = cv2.VideoCapture(str(Path(directory) / Path(updated.evidence_clip_url).name))
            try:
                self.assertAlmostEqual(capture.get(cv2.CAP_PROP_FRAME_COUNT) / capture.get(cv2.CAP_PROP_FPS), 4, delta=0.15)
            finally:
                capture.release()

    def test_two_cameras_share_writer_without_stealing_updates(self):
        with TemporaryDirectory() as directory, EvidenceWriter(Path(directory)) as writer:
            engines = {}
            alerts = {}
            for camera, value in [('a', 40), ('b', 200)]:
                zones, rules = synthetic_config(camera)
                engine = RuleEngine(camera, zones, rules, evidence_writer=writer)
                engines[camera] = engine
                for tf in scenario('exit_bag', camera)[:51]:
                    for alert in engine.update(np.full((120, 160, 3), value, np.uint8), tf)[1]:
                        alerts[camera] = alert
            for camera, engine in engines.items():
                updates = engine.drain_evidence()
                self.assertEqual(len(updates), 1)
                self.assertEqual(updates[0].camera_id, camera)
                self.assertEqual(updates[0].alert_id, alerts[camera].id)
            self.assertNotEqual(alerts['a'].id, alerts['b'].id)

    def test_recorded_video_and_saved_tracks_produce_ready_evidence(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.mp4'
            video = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), 10, (160, 120))
            self.assertTrue(video.isOpened())
            frames = scenario('exit_bag')[:81]
            try:
                for tf in frames:
                    image = np.full((120, 160, 3), 120, np.uint8)
                    cv2.putText(image, 'SYNTHETIC', (5, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
                    video.write(image)
            finally:
                video.release()
            tracks = Path(directory) / 'synthetic.tracks.jsonl'
            tracks.write_text(''.join(tf.model_dump_json() + '\n' for tf in frames))
            from engine.replay import read_frames
            with EvidenceWriter(Path(directory) / 'evidence') as writer:
                alerts = replay_clip(path, read_frames(tracks), evidence_writer=writer)
            self.assertEqual(len(alerts), 1)
            self.assertEqual(alerts[0].ts, 5)
            self.assertEqual(alerts[0].evidence_status, 'ready')
            self.assertIsNotNone(alerts[0].evidence_clip_url)

    def test_reviewed_alert_evidence_survives_engine_reset(self):
        with TemporaryDirectory() as directory, EvidenceWriter(Path(directory)) as writer:
            zones, rules = synthetic_config()
            engine = RuleEngine('cam_exit', zones, rules, evidence_writer=writer)
            alerts = []
            image = np.zeros((120, 160, 3), np.uint8)
            for tf in scenario('exit_bag')[:51]:
                alerts.extend(engine.update(image, tf)[1])
            engine.reset()
            updates = engine.drain_evidence()
            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].alert_id, alerts[0].id)
