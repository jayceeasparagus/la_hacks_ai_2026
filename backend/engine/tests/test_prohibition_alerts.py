import unittest

from app.models import Rule, Track
from engine.alerts import is_prohibition, obstruction_alert


def rule(rule_id, name, objects, zone='hallway', severity='review', duration=1):
    return Rule(id=rule_id, name=name, type='persistent_object', objects=objects, zone=zone,
                duration_seconds=duration, severity=severity)


def title(rule, object_class, zone_name='Hallway'):
    track = Track(track_id=1, object_class=object_class, bbox=(0.3, 0.3, 0.5, 0.7),
                  confidence=0.9)
    return obstruction_alert(incident_id='inc', camera_id='cam', rule=rule, track=track,
                             ts=2, elapsed=1.2, confidence=0.9, zone_name=zone_name,
                             created_at='2026-10-17T00:00:00Z').title


BAGS = ['backpack', 'handbag', 'suitcase']


class ProhibitionAlertTests(unittest.TestCase):
    def test_no_bags_names_the_object(self):
        self.assertEqual(title(rule('no_bags', 'No-bag policy', BAGS), 'backpack'),
                         'Possible backpack in view')

    def test_suffixed_id_is_still_a_prohibition(self):
        self.assertEqual(title(rule('no_bags_2', 'No-bag policy', BAGS), 'handbag'),
                         'Possible handbag in view')

    def test_no_chairs(self):
        self.assertEqual(title(rule('no_chairs', 'No-chair policy', ['chair']), 'chair'),
                         'Possible chair in view')

    def test_prohibition_beats_exit_wording(self):
        no_bags = rule('no_bags', 'No-bag policy', BAGS, zone='emergency_exit')
        self.assertEqual(title(no_bags, 'backpack', zone_name='emergency_exit'),
                         'Possible backpack in view')

    def test_unattended_bag_wording_unchanged(self):
        unattended = rule('unattended_bag', 'Unattended bag', ['backpack'], zone='lobby',
                          duration=2)
        self.assertFalse(is_prohibition(unattended))
        self.assertEqual(title(unattended, 'backpack', zone_name='Lobby'),
                         'Possible unattended bag')

    def test_blocked_exit_wording_unchanged(self):
        blocked = rule('blocked_exit', 'Blocked exit', BAGS + ['chair'], zone='emergency_exit',
                       severity='urgent', duration=5)
        self.assertEqual(title(blocked, 'chair', zone_name='Emergency exit'),
                         'Possible exit obstruction')

    def test_observation_sentence_kept(self):
        track = Track(track_id=1, object_class='backpack', bbox=(0.3, 0.3, 0.5, 0.7),
                      confidence=0.9)
        alert = obstruction_alert(incident_id='inc', camera_id='cam',
                                  rule=rule('no_bags', 'No-bag policy', BAGS), track=track,
                                  ts=2, elapsed=1.2, confidence=0.9, zone_name=None,
                                  created_at='2026-10-17T00:00:00Z')
        self.assertEqual(alert.observation,
                         'A backpack was observed in view for 1.2 seconds, '
                         'allowing brief detection gaps.')


if __name__ == '__main__':
    unittest.main()
