"""Validate the approved shared boundaries."""

import unittest

from pydantic import ValidationError

from app.models import CompileResult, Rule, TrackFrame, Verdict


class ContractTests(unittest.TestCase):
    def rule(self, **changes):
        data = dict(id='blocked_exit', name='Exit obstruction',
                    type='persistent_object', objects=['backpack', 'chair'],
                    zone='emergency_exit', duration_seconds=5, severity='urgent')
        return dict(data, **changes)

    def test_demo_rules_round_trip(self):
        result = CompileResult.model_validate({'rules': [
            self.rule(),
            self.rule(id='clear_bag', name='Clear bag', type='object_attribute',
                      objects=['backpack', 'handbag', 'suitcase'],
                      attribute={'name': 'transparent', 'expected': True},
                      zone='main_entrance', severity='review', duration_seconds=1),
            self.rule(id='pro_camera', name='Camera review', type='object_attribute',
                      objects=['camera'], attribute={'name': 'professional', 'expected': False},
                      zone='main_entrance', severity='review', duration_seconds=1),
        ]})
        self.assertEqual(CompileResult.model_validate_json(result.model_dump_json()), result)
        self.assertEqual(len(result.rules), 3)

    def test_capability_and_duration_limits(self):
        for changes in [dict(objects=['person']), dict(duration_seconds=0),
                        dict(duration_seconds=601), dict(duration_seconds=float('nan')),
                        dict(type='object_attribute'),
                        dict(type='object_attribute', objects=['chair'],
                             attribute={'name': 'transparent', 'expected': True})]:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                Rule.model_validate(self.rule(**changes))

    def test_unknown_model_output_fields_are_rejected(self):
        with self.assertRaises(ValidationError):
            Rule.model_validate(self.rule(execute='arbitrary action'))

    def test_verdict_requires_actual_boolean_or_null(self):
        for answer in [True, False, None]:
            self.assertIs(Verdict(answer=answer, confidence=0.9, reason='test').answer, answer)
        for answer in ['yes', 'no', 'false', 1]:
            with self.subTest(answer=answer), self.assertRaises(ValidationError):
                Verdict(answer=answer, confidence=0.9, reason='test')

    def test_tracks_reject_invalid_geometry_and_duplicate_ids(self):
        track = dict(track_id=1, object_class='backpack', bbox=[0.2, 0.2, 0.4, 0.7],
                     confidence=0.95)
        frame = dict(camera_id='cam_exit', ts=1, tracks=[track])
        self.assertEqual(TrackFrame.model_validate(frame).tracks[0].track_id, 1)
        for tracks in [[track, track], [dict(track, bbox=[0.8, 0.2, 0.2, 0.7])],
                       [dict(track, bbox=[0.2, 0.2, 1.1, 0.7])]]:
            with self.subTest(tracks=tracks), self.assertRaises(ValidationError):
                TrackFrame.model_validate(dict(frame, tracks=tracks))

    def test_json_schema_can_be_generated(self):
        self.assertEqual(CompileResult.model_json_schema()['type'], 'object')


if __name__ == '__main__':
    unittest.main()
