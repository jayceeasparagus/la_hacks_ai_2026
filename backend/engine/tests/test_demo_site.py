"""The site safety demo: cached verdicts, whole-frame cameras and draft track files."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.models import Rule, Track, Zone
from engine.engine import InlineExecutor, RuleEngine, crop_score
from engine.replay import read_frames
from engine.tests.test_attributes import CREATED, FakeVerifier, frame, image, verdict
from engine.zones import is_whole_frame

WHOLE = Zone(id='site_frame', camera_id='cam_site', name='Construction site',
             polygon=[(0, 0), (1, 0), (1, 1), (0, 1)])


def gear_rule(attribute):
    return Rule(id=attribute, name='Gear policy', type='object_attribute', objects=['person'],
                zone=WHOLE.id, attribute={'name': attribute, 'expected': True}, duration_seconds=1,
                severity='review')


class CachedVerdictTests(unittest.TestCase):
    def run_engine(self, lookup, verifier, track_id=7):
        engine = RuleEngine('cam_site', [WHOLE], [gear_rule('hard_hat')], session_id='test',
                            clock=lambda: CREATED, verifier=verifier, executor=InlineExecutor(),
                            verdict_lookup=lookup)
        alerts = []
        for tick in range(15):
            _, new = engine.update(image(), frame(tick / 10, 'person', track_id=track_id, camera='cam_site'))
            alerts.extend(new)
        return engine, alerts + engine.drain()

    def test_known_track_is_answered_from_the_cache(self):
        asked = []

        def lookup(track_id, check):
            asked.append((track_id, check))
            return verdict(False, 'baseball cap, no hard hat', 1.0)

        verifier = FakeVerifier(verdict(True))
        engine, alerts = self.run_engine(lookup, verifier)
        self.assertEqual(asked, [(7, 'hard_hat')])
        self.assertEqual(verifier.calls, [])  # never sent to the live verifier
        self.assertEqual([a.title for a in alerts], ['Possible missing hard hat'])
        # A whole-frame zone is never named in the alert.
        self.assertEqual(alerts[0].observation,
                         'A person is probably not wearing a hard hat (verifier: baseball cap, no hard hat).')
        self.assertEqual(engine.verdicts()[('hard_hat', 7)].answer, False)

    def test_unknown_track_goes_to_the_live_verifier(self):
        verifier = FakeVerifier(verdict(True, 'yellow hard hat'))
        engine, alerts = self.run_engine(lambda track_id, check: None, verifier)
        self.assertEqual(len(verifier.calls), 1)
        self.assertEqual(alerts, [])
        self.assertEqual(engine.verdicts()[('hard_hat', 7)].reason, 'yellow hard hat')

    def test_central_views_are_preferred(self):
        def track(x1, x2):
            return Track(track_id=1, object_class='person', bbox=(x1, 0.2, x2, 0.8), confidence=0.9)
        self.assertGreater(crop_score(track(0.4, 0.6)), crop_score(track(0.8, 1.0)))
        self.assertGreater(crop_score(track(0.3, 0.7)), crop_score(track(0.4, 0.6)))  # bigger still wins

    def test_whole_frame(self):
        self.assertTrue(is_whole_frame(WHOLE.polygon))
        self.assertFalse(is_whole_frame([(0, 0), (0.5, 0), (0.5, 1), (0, 1)]))


class DraftTrackFileTests(unittest.TestCase):
    def test_person1_draft_lines_are_converted(self):
        lines = [
            {'camera_id': 'clip', 'frame_index': 0, 'ts': 0.0, 'width': 1280, 'height': 720,
             'tracks': [{'track_id': 1, 'class_name': 'person', 'conf': 0.9, 'bbox': [0.2, 0.0, 0.6, 1.0]},
                        {'track_id': 2, 'class_name': 'car', 'conf': 0.8, 'bbox': [0.1, 0.1, 0.2, 0.2]}]},
            {'camera_id': 'clip', 'frame_index': 1, 'ts': 0.04, 'width': 1280, 'height': 720,
             'tracks': [{'track_id': 1, 'class_name': 'person', 'conf': 0.91, 'bbox': [0.21, 0.0, 0.6, 1.0]}]},
        ]
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'clip.tracks.jsonl'
            path.write_text(''.join(json.dumps(line) + '\n' for line in lines), encoding='utf-8')
            frames = list(read_frames(path))
        self.assertEqual([tf.ts for tf in frames], [0.0, 0.04])
        self.assertEqual([[t.track_id for t in tf.tracks] for tf in frames], [[1], [1]])  # 'car' dropped
        self.assertEqual(frames[0].tracks[0].object_class, 'person')
        self.assertAlmostEqual(frames[1].tracks[0].confidence, 0.91)

    def test_backwards_draft_timestamps_are_rejected(self):
        line = {'camera_id': 'clip', 'frame_index': 0, 'ts': 5.0, 'tracks': []}
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'clip.tracks.jsonl'
            path.write_text(json.dumps(line) + '\n' + json.dumps({**line, 'ts': 1.0}) + '\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, r'clip.tracks.jsonl:2: timestamps go backwards'):
                list(read_frames(path))


if __name__ == '__main__':
    unittest.main()
