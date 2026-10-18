import threading
import time
import unittest

import numpy as np

from app.demo import demo_rules, demo_zones
from app.models import Track, TrackFrame, Verdict
from engine.engine import RuleEngine
from engine.verification import StubVerifier, VerificationScheduler


class AttributeEngineTests(unittest.TestCase):
    def engine(self, scheduler, rule_index=0):
        return RuleEngine('cam_entrance', demo_zones(), [demo_rules()[rule_index]],
                          scheduler=scheduler, session_id='test',
                          clock=lambda: '2026-10-17T00:00:00Z')

    def frame(self, ts, track_id=1, object_class='backpack',
              bbox=(0.3, 0.3, 0.5, 0.7), confidence=0.9, empty=False):
        return TrackFrame(camera_id='cam_entrance', ts=ts, tracks=[] if empty else [
            Track(track_id=track_id, object_class=object_class,
                  bbox=bbox, confidence=confidence)])

    def run_frames(self, engine, *, answer=None, object_class='backpack'):
        alerts = []
        image = np.full((200, 300, 3), 150, np.uint8)
        for tick in range(16):
            alerts.extend(engine.update(image, self.frame(tick / 10, object_class=object_class))[1])
        alerts.extend(engine.drain_verifications())
        return alerts

    def test_clear_bag_is_compliant_and_checked_once(self):
        stub = StubVerifier({'transparent_bag': Verdict(answer=True, confidence=0.9, reason='test clear')})
        with VerificationScheduler(stub) as scheduler:
            engine = self.engine(scheduler)
            self.assertEqual(self.run_frames(engine), [])
            states, alerts = engine.update(np.zeros((200, 300, 3), np.uint8), self.frame(1.6))
            self.assertEqual(states[0].phase, 'compliant')
            self.assertEqual(alerts, [])
            self.assertEqual(stub.calls, ['transparent_bag'])

    def test_opaque_bag_creates_one_hedged_alert(self):
        stub = StubVerifier({'transparent_bag': Verdict(answer=False, confidence=0.84, reason='test opaque')})
        with VerificationScheduler(stub) as scheduler:
            alerts = self.run_frames(self.engine(scheduler))
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].ts, 1)
        self.assertEqual(alerts[0].confidence, 0.84)
        self.assertIn('probably opaque', alerts[0].observation)

    def test_unclear_becomes_manual_review(self):
        with VerificationScheduler(StubVerifier()) as scheduler:
            alerts = self.run_frames(self.engine(scheduler))
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].title, 'Manual review required')
        self.assertIn('stub verifier', alerts[0].observation)

    def test_professional_camera_expected_false(self):
        stub = StubVerifier({'professional_camera': Verdict(answer=True, confidence=0.9, reason='test lens')})
        with VerificationScheduler(stub) as scheduler:
            alerts = self.run_frames(self.engine(scheduler, 1), object_class='camera')
        self.assertEqual(len(alerts), 1)
        self.assertIn('Possible professional-style camera', alerts[0].observation)
        self.assertEqual(stub.calls, ['professional_camera'])

    def test_short_visit_does_not_submit(self):
        stub = StubVerifier()
        with VerificationScheduler(stub) as scheduler:
            engine = self.engine(scheduler)
            image = np.zeros((200, 300, 3), np.uint8)
            for tick in range(10):
                self.assertEqual(engine.update(image, self.frame(tick / 10))[1], [])
            engine.update(image, self.frame(1, empty=True))
            self.assertEqual(engine.drain_verifications(), [])
            self.assertEqual(stub.calls, [])

    def test_best_crop_preserves_large_confident_earlier_frame(self):
        seen = []
        def provider(crop, check):
            seen.append(crop.copy())
            return Verdict(answer=False, confidence=0.9, reason='test')
        with VerificationScheduler(provider) as scheduler:
            engine = self.engine(scheduler)
            alerts = []
            engine.update(np.full((200, 300, 3), 200, np.uint8), self.frame(0))
            for tick in range(1, 11):
                alerts.extend(engine.update(np.zeros((200, 300, 3), np.uint8), self.frame(
                    tick / 10, bbox=(0.35, 0.4, 0.45, 0.6), confidence=0.7))[1])
            alerts.extend(engine.drain_verifications())
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].mean(), 200)
        self.assertEqual(alerts[0].bbox, (0.3, 0.3, 0.5, 0.7))

    def test_slow_verifier_does_not_block_frames(self):
        release = threading.Event()
        def provider(crop, check):
            release.wait(2)
            return Verdict(answer=True, confidence=1, reason='test')
        with VerificationScheduler(provider) as scheduler:
            engine = self.engine(scheduler)
            image = np.zeros((200, 300, 3), np.uint8)
            for tick in range(10):
                engine.update(image, self.frame(tick / 10))
            started = time.monotonic()
            states, alerts = engine.update(image, self.frame(1))
            self.assertLess(time.monotonic() - started, 0.1)
            self.assertEqual(states[0].phase, 'verifying')
            self.assertEqual(alerts, [])
            release.set()
            self.assertEqual(engine.drain_verifications(), [])

    def test_reset_discards_inflight_results(self):
        release, started = threading.Event(), threading.Event()
        def provider(crop, check):
            started.set()
            release.wait(2)
            return Verdict(answer=False, confidence=1, reason='old session')
        with VerificationScheduler(provider) as scheduler:
            engine = self.engine(scheduler)
            image = np.zeros((200, 300, 3), np.uint8)
            for tick in range(11):
                engine.update(image, self.frame(tick / 10))
            self.assertTrue(started.wait(1))
            engine.reset()
            release.set()
            self.assertEqual(engine.drain_verifications(), [])
            self.assertEqual(engine.poll_verifications(), [])

    def test_same_track_reentry_reuses_verdict_but_new_incident(self):
        stub = StubVerifier({'transparent_bag': Verdict(answer=False, confidence=0.9, reason='test')})
        with VerificationScheduler(stub) as scheduler:
            engine = self.engine(scheduler)
            alerts = self.run_frames(engine)
            image = np.zeros((200, 300, 3), np.uint8)
            for tick in range(50, 66):
                alerts.extend(engine.update(image, self.frame(tick / 10))[1])
            alerts.extend(engine.drain_verifications())
        self.assertEqual(len(alerts), 2)
        self.assertNotEqual(alerts[0].incident_id, alerts[1].incident_id)
        self.assertEqual(stub.calls, ['transparent_bag'])

    def test_no_image_requires_review_without_calling_verifier(self):
        stub = StubVerifier()
        with VerificationScheduler(stub) as scheduler:
            engine = self.engine(scheduler)
            alerts = []
            for tick in range(11):
                alerts.extend(engine.update(None, self.frame(tick / 10))[1])
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].title, 'Manual review required')
        self.assertEqual(stub.calls, [])

    def test_wrong_object_and_outside_zone_are_ignored(self):
        stub = StubVerifier()
        with VerificationScheduler(stub) as scheduler:
            engine = self.engine(scheduler)
            image = np.zeros((200, 300, 3), np.uint8)
            for tick in range(21):
                self.assertEqual(engine.update(image, self.frame(tick / 10,
                    object_class='chair'))[1], [])
            self.assertEqual(stub.calls, [])

    def test_attribute_tracking_id_recovery_does_not_repeat_check(self):
        stub = StubVerifier({'transparent_bag': Verdict(answer=False, confidence=0.9, reason='test')})
        with VerificationScheduler(stub) as scheduler:
            engine = self.engine(scheduler)
            image = np.zeros((200, 300, 3), np.uint8)
            alerts = []
            for tick in range(26):
                alerts.extend(engine.update(image, self.frame(tick / 10,
                    track_id=1 if tick < 6 else 2))[1])
            alerts.extend(engine.drain_verifications())
        self.assertEqual(len(alerts), 1)
        self.assertEqual(stub.calls, ['transparent_bag'])

    def test_two_camera_engines_do_not_share_track_results(self):
        stub = StubVerifier({'transparent_bag': Verdict(answer=False, confidence=0.9, reason='test')})
        with VerificationScheduler(stub) as scheduler:
            a = self.engine(scheduler)
            zone = demo_zones()[0].model_copy(update={'camera_id': 'other'})
            b = RuleEngine('other', [zone], [demo_rules()[0]], scheduler=scheduler,
                           session_id='test')
            image = np.zeros((200, 300, 3), np.uint8)
            alerts = []
            for tick in range(11):
                frame = self.frame(tick / 10)
                alerts.extend(a.update(image, frame)[1])
                alerts.extend(b.update(image, frame.model_copy(update={'camera_id': 'other'}))[1])
            alerts.extend(a.drain_verifications())
            alerts.extend(b.drain_verifications())
        self.assertEqual(len(alerts), 2)
        self.assertEqual({alert.camera_id for alert in alerts}, {'cam_entrance', 'other'})
        self.assertEqual(len(stub.calls), 2)
