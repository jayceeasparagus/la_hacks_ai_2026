from concurrent.futures import ThreadPoolExecutor
import unittest

from app.models import Track, TrackFrame
from engine.engine import RuleEngine
from engine.fake_tracks import SCENARIOS, scenario, synthetic_config


class TemporalEngineTests(unittest.TestCase):
    def engine(self, camera='cam_exit'):
        zones, rules = synthetic_config(camera)
        return RuleEngine(camera, zones, rules, session_id='test',
                          clock=lambda: '2026-10-17T00:00:00Z')


    def frame(self, ts, track_id=1, bbox=(0.3, 0.3, 0.5, 0.7), confidence=0.9,
              camera='cam_exit', empty=False):
        return TrackFrame(camera_id=camera, ts=ts, tracks=[] if empty else [
            Track(track_id=track_id, object_class='backpack', bbox=bbox,
                  confidence=confidence)])


    def run_frames(self, engine, frames):
        alerts = []
        for frame in frames:
            _, new = engine.update(None, frame)
            alerts.extend(new)
        return alerts


    def test_threshold_not_before_five_seconds(self):
        engine = self.engine()
        for tick in range(50):
            _, alerts = engine.update(None, self.frame(tick / 10))
            self.assertEqual(alerts, [])
        states, alerts = engine.update(None, self.frame(5))
        self.assertEqual(len(alerts), 1)
        self.assertEqual(states[0].phase, 'alerted')
        self.assertEqual(alerts[0].evidence_status, 'unavailable')
        self.assertIsNone(alerts[0].evidence_clip_url)


    def test_one_alert_per_incident(self):
        engine = self.engine()
        alerts = self.run_frames(engine, [self.frame(tick / 10) for tick in range(81)])
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].ts, 5)


    def test_missing_frame_cannot_trigger(self):
        engine = self.engine()
        self.run_frames(engine, [self.frame(tick / 10) for tick in range(48)])
        self.assertEqual(engine.update(None, self.frame(5, empty=True))[1], [])
        self.assertEqual(len(engine.update(None, self.frame(5.4))[1]), 1)


    def test_exact_grace_boundary_and_long_gap(self):
        for gap, expected in [(1.0, 1), (1.1, 0)]:
            with self.subTest(gap=gap):
                engine = self.engine()
                self.run_frames(engine, [self.frame(tick / 10) for tick in range(41)])
                self.assertEqual(len(engine.update(None, self.frame(4 + gap))[1]), expected)


    def test_simultaneous_overlapping_objects_do_not_merge(self):
        engine = self.engine()
        alerts = []
        for tick in range(61):
            frame = self.frame(tick / 10)
            frame.tracks.append(frame.tracks[0].model_copy(update={'track_id': 2}))
            alerts.extend(engine.update(None, frame)[1])
        self.assertEqual({alert.track_id for alert in alerts}, {1, 2})
        self.assertEqual(len(alerts), 2)


    def test_ambiguous_id_recovery_does_not_merge(self):
        engine = self.engine()
        for tick in range(41):
            frame = self.frame(tick / 10)
            frame.tracks.append(frame.tracks[0].model_copy(update={'track_id': 2}))
            engine.update(None, frame)
        # Both vanished tracks match this new box: start a fresh timer.
        for tick in range(41, 91):
            self.assertEqual(engine.update(None, self.frame(tick / 10, track_id=3))[1], [])
        alerts = engine.update(None, self.frame(9.1, track_id=3))[1]
        self.assertEqual(len(alerts), 1)


    def test_outside_track_is_not_reidentified(self):
        engine = self.engine()
        self.run_frames(engine, [self.frame(tick / 10) for tick in range(41)])
        frame = self.frame(4.1, track_id=2)
        frame.tracks.append(Track(track_id=1, object_class='backpack',
                                  bbox=(0.01, 0.1, 0.1, 0.7), confidence=0.9))
        self.assertEqual(engine.update(None, frame)[1], [])
        for tick in range(42, 91):
            self.assertEqual(engine.update(None, self.frame(tick / 10, track_id=2))[1], [])


    def test_id_switch_after_alert_does_not_duplicate(self):
        engine = self.engine()
        frames = [self.frame(tick / 10, track_id=1 if tick < 60 else 2)
                  for tick in range(81)]
        self.assertEqual(len(self.run_frames(engine, frames)), 1)


    def test_alert_closes_after_exact_two_seconds(self):
        engine = self.engine()
        self.run_frames(engine, [self.frame(tick / 10) for tick in range(61)])
        states, _ = engine.update(None, self.frame(7.9, empty=True))
        self.assertFalse(any(state.phase == 'cleared' for state in states))
        states, _ = engine.update(None, self.frame(8, empty=True))
        self.assertEqual([state.phase for state in states], ['cleared'])
        self.assertEqual(engine.update(None, self.frame(8.1, empty=True)), ([], []))


    def test_confidence_is_mean_of_observed_detections(self):
        engine = self.engine()
        alerts = self.run_frames(engine, [self.frame(tick / 10, confidence=0.8 if tick < 50 else 1)
                                           for tick in range(51)])
        self.assertAlmostEqual(alerts[0].confidence, (50 * 0.8 + 1) / 51)


    def test_wrong_camera_and_rewind_do_not_mutate_state(self):
        engine = self.engine()
        engine.update(None, self.frame(1))
        for frame in [self.frame(0), self.frame(1), self.frame(2, camera='other')]:
            with self.subTest(frame=frame), self.assertRaises(ValueError):
                engine.update(None, frame)
        self.assertEqual(engine.update(None, self.frame(2))[0][0].elapsed_seconds, 1)


    def test_reset_allows_rewind_and_uses_new_incident_ids(self):
        engine = self.engine()
        frames = [self.frame(tick / 10) for tick in range(51)]
        first = self.run_frames(engine, frames)[0]
        engine.reset()
        second = self.run_frames(engine, frames)[0]
        self.assertNotEqual(first.id, second.id)


    def test_disabled_rules_and_configuration_copy(self):
        zones, rules = synthetic_config()
        engine = RuleEngine('cam_exit', zones, rules)
        rules[0].duration_seconds = 600
        zones[0].polygon.clear()
        self.assertEqual(len(self.run_frames(engine, scenario('exit_bag'))), 1)
        zones, rules = synthetic_config()
        rules[0].enabled = False
        engine = RuleEngine('cam_exit', zones, rules)
        self.assertEqual(self.run_frames(engine, scenario('exit_bag')), [])


    def test_missing_zone_and_invalid_polygon_rejected(self):
        zones, rules = synthetic_config()
        with self.assertRaises(ValueError):
            RuleEngine('cam_exit', [], rules)
        zones[0].polygon = [(0, 0), (1, 1), (1, 0), (0, 1)]
        with self.assertRaises(ValueError):
            RuleEngine('cam_exit', zones, rules)


if __name__ == '__main__':
    unittest.main()
