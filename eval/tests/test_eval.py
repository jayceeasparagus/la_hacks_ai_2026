from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorded_eval import evaluate, load_cases, score


class EvaluationTests(unittest.TestCase):
    def alert(self, name, ts, incident=None):
        return SimpleNamespace(id=name, ts=ts, incident_id=incident or name)

    def test_exact_counts_duplicates_false_alerts_and_misses(self):
        alerts = [self.alert('a',5), self.alert('a2',6,'a'),
                  self.alert('b',5.1), self.alert('false',30)]
        result=score(alerts, [[5,5.2], [10,10.2]])
        self.assertEqual(result['correct_detections'],1)
        self.assertEqual(result['duplicate_alerts'],2)
        self.assertEqual(result['false_alerts'],1)
        self.assertEqual(result['missed_events'],1)

    def test_two_objects_can_match_same_time_window(self):
        result=score([self.alert('a',5),self.alert('b',5)], [[5,5.1],[5,5.1]])
        self.assertEqual(result['correct_detections'],2)
        self.assertEqual(result['duplicate_alerts'],0)

    def test_negative_case(self):
        self.assertEqual(score([], [])['false_alerts'],0)
        self.assertEqual(score([self.alert('a',5)], [])['false_alerts'],1)

    def test_repository_case_manifest_has_twenty_valid_cases(self):
        cases=load_cases(Path(__file__).resolve().parents[1] / 'recorded_cases.csv')
        self.assertEqual(len(cases),20)

    def test_empty_case_file_fails_loudly(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'cases.csv'
            path.write_text('case_id\n')
            with self.assertRaises(ValueError): load_cases(path)
