from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest import mock

import numpy as np

from app.demo import demo_rules, demo_zones
from app.models import Rule, Track, TrackFrame, Verdict, Zone
from engine import replay as replay_module
from engine.crop import crop
from engine.engine import MAX_ALERT_FRAMES, InlineExecutor, RuleEngine
from engine.fake_tracks import synthetic_config
from engine.replay import replay

CREATED = '2026-10-17T00:00:00Z'


def verdict(answer, reason='fake verdict', confidence=0.9):
    return Verdict(answer=answer, confidence=confidence, reason=reason)


class FakeVerifier:
    """Returns the given verdicts in order, repeating the last one."""

    def __init__(self, *verdicts):
        self.verdicts = list(verdicts)
        self.calls = []

    def __call__(self, image, check):
        self.calls.append((image, check))
        result = self.verdicts[min(len(self.calls), len(self.verdicts)) - 1]
        if isinstance(result, Exception):
            raise result
        return result


def frame(ts, object_class='backpack', track_id=1, bbox=(0.3, 0.3, 0.5, 0.7),
          camera='cam_entrance', empty=False):
    return TrackFrame(camera_id=camera, ts=ts, tracks=[] if empty else [
        Track(track_id=track_id, object_class=object_class, bbox=bbox, confidence=0.9)])


def image(value=50):
    return np.full((200, 400, 3), value, np.uint8)


class AttributeRuleTests(unittest.TestCase):
    def engine(self, verifier, camera='cam_entrance', zones=None, rules=None, **kwargs):
        kwargs.setdefault('executor', InlineExecutor())
        return RuleEngine(camera, zones or demo_zones(), rules or demo_rules(),
                          session_id='test', clock=lambda: CREATED, verifier=verifier,
                          **kwargs)

    def run_frames(self, engine, frames, images=None):
        states, alerts = [], []
        for index, tf in enumerate(frames):
            new_states, new_alerts = engine.update(
                None if images is None else images[index], tf)
            states.append(new_states)
            alerts.extend(new_alerts)
        return states, alerts + engine.drain()

    def test_clear_bag_is_compliant(self):
        verifier = FakeVerifier(verdict(True, 'clear plastic bag'))
        engine = self.engine(verifier)
        frames = [frame(tick / 10) for tick in range(21)]
        states, alerts = self.run_frames(engine, frames, [image()] * len(frames))
        self.assertEqual(alerts, [])
        self.assertEqual([state.phase for state in states[9]], ['timing'])
        self.assertEqual([state.phase for state in states[10]], ['verifying'])
        self.assertEqual([state.phase for state in states[-1]], ['compliant'])
        self.assertEqual(len(verifier.calls), 1)
        crop_image, check = verifier.calls[0]
        self.assertEqual(check, 'transparent_bag')
        self.assertIsInstance(crop_image, np.ndarray)

    def test_opaque_bag_alerts_once(self):
        engine = self.engine(FakeVerifier(verdict(False, 'black fabric backpack')))
        states, alerts = self.run_frames(engine, [frame(tick / 10) for tick in range(31)])
        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert.title, 'Possible non-clear bag')
        self.assertEqual(alert.observation, 'A backpack in the Main entrance zone is '
                         'probably not a clear bag (verifier: black fabric backpack).')
        self.assertEqual((alert.rule_id, alert.camera_id, alert.severity),
                         ('clear_bag', 'cam_entrance', 'review'))
        self.assertEqual((alert.track_id, alert.object_class), (1, 'backpack'))
        self.assertEqual(alert.confidence, 0.9)
        self.assertAlmostEqual(alert.ts, 1.1)  # verdict polled at the next update
        self.assertAlmostEqual(alert.elapsed_seconds, 1.1)
        self.assertEqual(alert.id, f'{alert.incident_id}:alert')
        self.assertEqual(alert.evidence_status, 'unavailable')
        self.assertEqual([state.phase for state in states[-1]], ['alerted'])

    def test_professional_camera_alerts(self):
        verifier = FakeVerifier(verdict(True, 'DSLR with long lens.'))
        _, alerts = self.run_frames(self.engine(verifier),
                                    [frame(tick / 10, 'camera') for tick in range(15)])
        self.assertEqual(verifier.calls[0][1], 'professional_camera')
        self.assertEqual([alert.title for alert in alerts], ['Possible professional camera'])
        self.assertEqual(alerts[0].observation, 'A camera in the Main entrance zone looks '
                         'like a professional-style camera (verifier: DSLR with long lens).')

    def test_unclear_verdict_needs_manual_review(self):
        engine = self.engine(FakeVerifier(verdict(None, 'verification timed out', 0)))
        _, alerts = self.run_frames(engine, [frame(tick / 10) for tick in range(15)])
        self.assertEqual([alert.title for alert in alerts], ['Manual review needed'])
        self.assertEqual(alerts[0].observation, "Couldn't tell whether the backpack in the "
                         'Main entrance zone is a clear bag (verification timed out).')
        self.assertEqual(alerts[0].severity, 'review')
        self.assertEqual(alerts[0].confidence, 0)

    def test_verifier_exception_needs_manual_review(self):
        engine = self.engine(FakeVerifier(RuntimeError('boom')))
        _, alerts = self.run_frames(engine, [frame(tick / 10) for tick in range(15)])
        self.assertEqual([alert.title for alert in alerts], ['Manual review needed'])
        self.assertIn('verification unavailable', alerts[0].observation)

    def test_no_frame_sends_none_crop(self):
        verifier = FakeVerifier(verdict(None, 'object too small to judge', 0))
        _, alerts = self.run_frames(self.engine(verifier),
                                    [frame(tick / 10) for tick in range(15)])
        self.assertIsNone(verifier.calls[0][0])
        self.assertEqual(len(alerts), 1)

    def test_brief_pass_never_verifies(self):
        verifier = FakeVerifier(verdict(False))
        frames = [frame(tick / 10, empty=tick >= 8) for tick in range(40)]
        _, alerts = self.run_frames(self.engine(verifier), frames)
        self.assertEqual((verifier.calls, alerts), ([], []))

    def test_one_verifier_call_per_incident(self):
        verifier = FakeVerifier(verdict(False))
        _, alerts = self.run_frames(self.engine(verifier),
                                    [frame(tick / 10) for tick in range(300)])
        self.assertEqual(len(verifier.calls), 1)
        self.assertEqual(len(alerts), 1)

    def test_reentry_after_close_verifies_again(self):
        verifier = FakeVerifier(verdict(False))
        frames = [frame(tick / 10, empty=20 <= tick < 50) for tick in range(70)]
        _, alerts = self.run_frames(self.engine(verifier), frames)
        self.assertEqual(len(verifier.calls), 2)
        self.assertEqual(len({alert.incident_id for alert in alerts}), 2)

    def test_best_observation_is_cropped(self):
        verifier = FakeVerifier(verdict(False))
        engine = self.engine(verifier)
        frames, images = [], []
        for tick in range(15):
            big = tick == 4
            frames.append(frame(tick / 10, bbox=(0.25, 0.25, 0.75, 0.75) if big
                                else (0.3, 0.3, 0.5, 0.7)))
            images.append(image(tick))
        _, alerts = self.run_frames(engine, frames, images)
        crop_image = verifier.calls[0][0]
        self.assertEqual(crop_image.shape, crop(images[4], (0.25, 0.25, 0.75, 0.75)).shape)
        self.assertTrue((crop_image == 4).all())
        self.assertEqual(alerts[0].bbox, (0.25, 0.25, 0.75, 0.75))
        best = engine.pop_alert_frame(alerts[0].id)
        self.assertTrue((best == 4).all())
        self.assertIsNone(engine.pop_alert_frame(alerts[0].id))
        images[4][:] = 99  # a reused capture buffer must not change the stored frame
        self.assertTrue((crop_image == 4).all())

    def test_reset_discards_pending_verification(self):
        release = threading.Event()
        calls = []

        def slow(crop_image, check):
            calls.append(check)
            release.wait(5)
            return verdict(False)

        with ThreadPoolExecutor(max_workers=1) as pool:
            engine = self.engine(slow, executor=pool)
            states, alerts = self.run_frames_without_drain(
                engine, [frame(tick / 10) for tick in range(12)])
            self.assertEqual(alerts, [])
            self.assertEqual([state.phase for state in states], ['verifying'])
            engine.reset()
            release.set()
        _, alerts = self.run_frames(engine, [frame(tick / 10, empty=True)
                                             for tick in range(5)])
        self.assertEqual(alerts, [])
        self.assertEqual(len(calls), 1)

    def run_frames_without_drain(self, engine, frames):
        alerts = []
        for tf in frames:
            states, new_alerts = engine.update(None, tf)
            alerts.extend(new_alerts)
        return states, alerts

    def test_busy_is_retried_after_a_second(self):
        now = [0.0]
        verifier = FakeVerifier(verdict(None, 'verification busy', 0), verdict(False))
        engine = self.engine(verifier, monotonic=lambda: now[0])
        _, alerts = self.run_frames_without_drain(
            engine, [frame(tick / 10) for tick in range(13)])
        self.assertEqual((len(verifier.calls), alerts), (1, []))
        now[0] = 0.9
        self.assertEqual(engine.update(None, frame(1.3))[1], [])
        self.assertEqual(len(verifier.calls), 1)
        now[0] = 1.0
        _, alerts = engine.update(None, frame(1.4))
        self.assertEqual(len(verifier.calls), 2)
        self.assertEqual([alert.title for alert in alerts], ['Possible non-clear bag'])

    def test_busy_twice_retried_then_manual_review(self):
        now = [0.0]
        verifier = FakeVerifier(verdict(None, 'verification busy', 0))
        engine = self.engine(verifier, monotonic=lambda: now[0])
        alerts = []
        for tick in range(40):
            now[0] = tick / 10
            alerts.extend(engine.update(None, frame(tick / 10))[1])
        self.assertEqual(len(verifier.calls), 3)
        self.assertEqual([alert.title for alert in alerts], ['Manual review needed'])
        self.assertIn('(verification busy)', alerts[0].observation)

    def test_two_cameras_keep_their_own_alerts(self):
        zones = [demo_zones()[0].model_copy(update={'id': f'{camera}_zone', 'camera_id': camera})
                 for camera in ('cam_a', 'cam_b')]
        rules = [demo_rules()[0].model_copy(update={'id': f'clear_bag_{camera}',
                                                    'zone': f'{camera}_zone'})
                 for camera in ('cam_a', 'cam_b')]
        verifier = FakeVerifier(verdict(False))
        with ThreadPoolExecutor(max_workers=2) as pool:
            engines = {camera: self.engine(verifier, camera, zones, rules, executor=pool)
                       for camera in ('cam_a', 'cam_b')}
            alerts = {camera: [] for camera in engines}
            for tick in range(15):
                for camera, engine in engines.items():
                    alerts[camera].extend(engine.update(None, frame(tick / 10, camera=camera))[1])
            for camera, engine in engines.items():
                alerts[camera].extend(engine.drain())
        for camera in engines:
            self.assertEqual([alert.camera_id for alert in alerts[camera]], [camera])
            self.assertEqual(alerts[camera][0].rule_id, f'clear_bag_{camera}')
        self.assertNotEqual(alerts['cam_a'][0].id, alerts['cam_b'][0].id)

    def test_default_owned_executor_does_not_block(self):
        verifier = FakeVerifier(verdict(False))
        engine = RuleEngine('cam_entrance', demo_zones(), demo_rules(), verifier=verifier)
        try:
            _, alerts = self.run_frames(engine, [frame(tick / 10) for tick in range(12)])
        finally:
            engine.close()
        self.assertEqual([alert.title for alert in alerts], ['Possible non-clear bag'])


class PersistentAlertTests(unittest.TestCase):
    def test_titles_depend_on_rule(self):
        zone = Zone(id='lobby', camera_id='cam_lobby', name='Lobby',
                    polygon=[(0.2, 0.2), (0.8, 0.2), (0.8, 0.9), (0.2, 0.9)])
        rule = Rule(id='unattended_bag', name='Unattended bag', type='persistent_object',
                    objects=['backpack'], zone='lobby', duration_seconds=2,
                    severity='review')
        engine = RuleEngine('cam_lobby', [zone], [rule])
        alerts = [alert for tick in range(25)
                  for alert in engine.update(None, frame(tick / 10, camera='cam_lobby'))[1]]
        self.assertEqual([alert.title for alert in alerts], ['Possible unattended bag'])
        zones, rules = synthetic_config()
        engine = RuleEngine('cam_exit', zones, rules)
        alerts = [alert for tick in range(51)
                  for alert in engine.update(None, frame(tick / 10, camera='cam_exit'))[1]]
        self.assertEqual([alert.title for alert in alerts], ['Possible exit obstruction'])

    def test_alert_frame_is_threshold_frame_and_bounded(self):
        zones, rules = synthetic_config()
        engine = RuleEngine('cam_exit', zones, rules)
        alerts = []
        for tick in range(51):
            alerts.extend(engine.update(image(tick), frame(tick / 10, camera='cam_exit'))[1])
        self.assertTrue((engine.pop_alert_frame(alerts[0].id) == 50).all())
        self.assertIsNone(engine.pop_alert_frame(alerts[0].id))
        for index in range(MAX_ALERT_FRAMES + 8):
            engine._remember_frame(f'alert-{index}', image())
        self.assertIsNone(engine.pop_alert_frame('alert-7'))
        self.assertIsNotNone(engine.pop_alert_frame('alert-8'))


class CropTests(unittest.TestCase):
    def test_padded_crop_matches_pixels(self):
        picture = np.arange(200 * 400 * 3, dtype=np.uint32).reshape(200, 400, 3)
        result = crop(picture, (0.25, 0.25, 0.75, 0.75), pad=0.25)
        self.assertEqual(result.shape, (150, 300, 3))
        self.assertTrue((result == picture[25:175, 50:350]).all())
        result[:] = 0
        self.assertNotEqual(picture[25, 50, 0], 0)

    def test_crop_clamps_to_image(self):
        picture = np.zeros((200, 400, 3), np.uint8)
        self.assertEqual(crop(picture, (0.0, 0.0, 0.5, 0.5), pad=0.5).shape, (150, 300, 3))
        # Padding extends left/top (170 px, 85 px); right/bottom clamp to the image.
        self.assertEqual(crop(picture, (0.5, 0.5, 1.0, 1.0)).shape, (115, 230, 3))
        self.assertEqual(crop(picture, (0.25, 0.25, 0.75, 0.75)).shape, (130, 260, 3))


class AttributeReplayTests(unittest.TestCase):
    def frames(self):
        entrance = [frame(tick / 10) for tick in range(21)]
        exit_ = [frame(tick / 10, camera='cam_exit') for tick in range(61)]
        return sorted(entrance + exit_, key=lambda tf: tf.ts)

    def test_demo_rules_replay(self):
        alerts = replay(self.frames(), demo_zones(), demo_rules())
        self.assertEqual([(alert.camera_id, alert.title) for alert in alerts],
                         [('cam_entrance', 'Manual review needed'),
                          ('cam_exit', 'Possible exit obstruction')])
        self.assertIn('no video frame in track replay', alerts[0].observation)
        again = replay(self.frames(), demo_zones(), demo_rules())
        self.assertEqual([alert.model_dump() for alert in alerts],
                         [alert.model_dump() for alert in again])

    def test_injected_verifier_and_final_drain(self):
        frames = [frame(tick / 10) for tick in range(11)]  # threshold on the last frame
        alerts = replay(frames, demo_zones(), demo_rules(),
                        verifier=FakeVerifier(verdict(False, 'leather bag')))
        self.assertEqual([alert.title for alert in alerts], ['Possible non-clear bag'])
        self.assertEqual(alerts[0].ts, 1.0)

    def test_cli_accepts_attribute_config(self):
        with TemporaryDirectory() as directory:
            tracks = Path(directory) / 'entrance.tracks.jsonl'
            tracks.write_text(''.join(tf.model_dump_json() + '\n' for tf in self.frames()),
                              encoding='utf-8')
            config = Path(directory) / 'config.json'
            config.write_text(json.dumps({
                'zones': [zone.model_dump(mode='json') for zone in demo_zones()],
                'rules': [rule.model_dump(mode='json') for rule in demo_rules()]}),
                encoding='utf-8')
            stdout, stderr = io.StringIO(), io.StringIO()
            argv = ['replay', str(tracks), '--config', str(config)]
            with mock.patch.object(sys, 'argv', argv), redirect_stdout(stdout), \
                    redirect_stderr(stderr):
                replay_module.main()
        self.assertEqual(len(stdout.getvalue().splitlines()), 2)
        self.assertIn('2 alert(s)', stderr.getvalue())
        self.assertIn('manual-review', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
