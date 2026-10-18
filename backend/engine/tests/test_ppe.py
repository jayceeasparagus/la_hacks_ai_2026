"""Construction-site safety gear rules: hard hats and hi-vis vests on people."""

import unittest

from app.models import Rule, Zone
from engine.engine import InlineExecutor, RuleEngine
from engine.tests.test_attributes import CREATED, FakeVerifier, frame, image, verdict

SITE = Zone(id='construction_zone', camera_id='cam_site', name='Construction zone',
            polygon=[(0.1, 0.1), (0.9, 0.1), (0.9, 0.95), (0.1, 0.95)])


def gear_rule(attribute):
    return Rule(id=attribute, name=attribute.replace('_', '-').capitalize() + ' policy',
                type='object_attribute', objects=['person'], zone=SITE.id,
                attribute={'name': attribute, 'expected': True}, duration_seconds=1,
                severity='review')


class SafetyGearTests(unittest.TestCase):
    def run_rule(self, rule, verifier):
        engine = RuleEngine('cam_site', [SITE], [rule], session_id='test', clock=lambda: CREATED,
                            verifier=verifier, executor=InlineExecutor())
        alerts = []
        for tick in range(21):
            _, new = engine.update(image(), frame(tick / 10, 'person', camera='cam_site'))
            alerts.extend(new)
        return alerts + engine.drain()

    def test_missing_hard_hat_alerts(self):
        verifier = FakeVerifier(verdict(False, 'bare head, no helmet'))
        alerts = self.run_rule(gear_rule('hard_hat'), verifier)
        self.assertEqual(verifier.calls[0][1], 'hard_hat')
        self.assertEqual([a.title for a in alerts], ['Possible missing hard hat'])
        self.assertEqual(alerts[0].observation, 'A person in the Construction zone zone is probably not '
                         'wearing a hard hat (verifier: bare head, no helmet).')

    def test_jeans_ban_alerts_when_jeans_are_worn(self):
        rule = gear_rule('jeans').model_copy(update={'attribute': {'name': 'jeans', 'expected': False}})
        rule = type(rule).model_validate(rule.model_dump())
        verifier = FakeVerifier(verdict(True, 'blue denim jeans'))
        alerts = self.run_rule(rule, verifier)
        self.assertEqual(verifier.calls[0][1], 'jeans')
        self.assertEqual([a.title for a in alerts], ['Possible jeans worn'])
        self.assertEqual(alerts[0].observation, 'A person in the Construction zone zone is probably '
                         'wearing jeans (verifier: blue denim jeans).')
        self.assertEqual(self.run_rule(rule, FakeVerifier(verdict(False, 'black joggers'))), [])

    def test_vest_worn_is_compliant(self):
        self.assertEqual(self.run_rule(gear_rule('safety_vest'), FakeVerifier(verdict(True, 'orange hi-vis vest'))), [])

    def test_unclear_vest_needs_manual_review(self):
        alerts = self.run_rule(gear_rule('safety_vest'), FakeVerifier(verdict(None, 'torso hidden')))
        self.assertEqual([a.title for a in alerts], ['Manual review needed'])
        self.assertIn('is wearing a safety vest (torso hidden)', alerts[0].observation)

    def test_people_are_not_allowed_in_persistent_rules(self):
        with self.assertRaises(ValueError):
            Rule(id='x', name='x', type='persistent_object', objects=['person'], zone=SITE.id,
                 duration_seconds=5, severity='urgent')


if __name__ == '__main__':
    unittest.main()
