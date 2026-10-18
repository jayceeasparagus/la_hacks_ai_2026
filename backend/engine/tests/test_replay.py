from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from engine.fake_tracks import SCENARIOS, write_scenarios
from engine.replay import read_frames, replay


class ReplayFileTests(unittest.TestCase):
    def test_saved_jsonl_replays_expected_incidents(self):
        with TemporaryDirectory() as directory:
            for path in write_scenarios(Path(directory)):
                name = path.name.removesuffix('.tracks.jsonl')
                with self.subTest(name=name):
                    actual = [round(alert.ts, 3) for alert in replay(read_frames(path))]
                    self.assertEqual(actual, SCENARIOS[name][1])

    def test_invalid_jsonl_reports_file_and_line(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.jsonl'
            path.write_text('\n{}\n')
            with self.assertRaisesRegex(ValueError, r'bad.jsonl:2: invalid TrackFrame'):
                list(read_frames(path))

    def test_empty_input_produces_no_alerts(self):
        self.assertEqual(replay([]), [])
