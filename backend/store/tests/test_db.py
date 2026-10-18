"""Alert persistence, filtering and the decision audit trail."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.demo import demo_rules
from app.models import Alert
from store import AlertStore


def make_alert(n: int, camera_id='cam_exit', created_at=None, **changes) -> Alert:
    rule = demo_rules()[2]
    data = dict(id=f'{camera_id}:s:{rule.id}:{n}:alert', incident_id=f'{camera_id}:s:{rule.id}:{n}',
                camera_id=camera_id, rule_id=rule.id, rule_name=rule.name, zone_id=rule.zone,
                track_id=n, object_class='backpack', bbox=(0.3, 0.3, 0.5, 0.7), ts=5.0 + n,
                created_at=created_at or f'2026-10-17T00:00:{n:02d}Z', elapsed_seconds=5.0,
                severity='urgent', title='Possible exit obstruction', observation='A backpack...',
                confidence=0.9, rule_snapshot=rule)
    return Alert(**dict(data, **changes))


class AlertStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = AlertStore(':memory:')

    def tearDown(self):
        self.store.close()

    def test_add_get_and_duplicate(self):
        alert = make_alert(1)
        self.assertTrue(self.store.add(alert))
        self.assertFalse(self.store.add(alert.model_copy(update={'title': 'changed'})))
        self.assertEqual(self.store.get(alert.id), alert)
        self.assertIsNone(self.store.get('missing'))

    def test_list_order_filters_pagination_and_total(self):
        for n in range(1, 6):
            self.store.add(make_alert(n, camera_id='cam_exit' if n % 2 else 'cam_entrance'))
        alerts, total = self.store.list()
        self.assertEqual(total, 5)
        self.assertEqual([alert.track_id for alert in alerts], [5, 4, 3, 2, 1])
        alerts, total = self.store.list(camera_id='cam_exit', limit=2)
        self.assertEqual(([alert.track_id for alert in alerts], total), ([5, 3], 3))
        alerts, total = self.store.list(camera_id='cam_exit', limit=2, offset=2)
        self.assertEqual(([alert.track_id for alert in alerts], total), ([1], 3))
        self.store.decide(make_alert(4).id.replace('cam_exit', 'cam_entrance'), 'confirmed',
                          '2026-10-17T01:00:00Z')
        self.assertEqual(self.store.list(status='reviewed')[1], 1)
        self.assertEqual(self.store.list(status='open')[1], 4)
        self.assertEqual(len(self.store.list(limit=0)[0]), 1)         # clamped to 1
        self.assertEqual(len(self.store.list(limit=10_000)[0]), 5)    # clamped to 500
        self.assertEqual(len(self.store.list(offset=-3)[0]), 5)
        with self.assertRaises(ValueError):
            self.store.list(status='closed')

    def test_order_uses_time_not_text(self):
        whole = make_alert(1, created_at='2026-10-17T00:00:01Z')
        fraction = make_alert(2, created_at='2026-10-17T00:00:01.500000Z')
        tie = make_alert(3, created_at='2026-10-17T00:00:01.500000+00:00')
        for alert in (whole, fraction, tie):
            self.store.add(alert)
        ids = [alert.id for alert in self.store.list()[0]]
        self.assertEqual(ids, sorted([fraction.id, tie.id]) + [whole.id])
        self.assertEqual(self.store.get(tie.id).created_at, '2026-10-17T00:00:01.500000+00:00')

    def test_decide_is_idempotent_and_audited(self):
        alert = make_alert(1)
        self.store.add(alert)
        first = self.store.decide(alert.id, 'confirmed', '2026-10-17T01:00:00Z')
        self.assertEqual((first.status, first.decision, first.decided_at),
                         ('reviewed', 'confirmed', '2026-10-17T01:00:00Z'))
        again = self.store.decide(alert.id, 'confirmed', '2026-10-17T02:00:00Z')
        self.assertEqual(again.decided_at, '2026-10-17T01:00:00Z')
        changed = self.store.decide(alert.id, 'dismissed', '2026-10-17T03:00:00Z')
        self.assertEqual((changed.decision, changed.decided_at), ('dismissed', '2026-10-17T03:00:00Z'))
        self.assertEqual(self.store.get(alert.id), changed)
        self.assertEqual(self.store.decisions(alert.id), [
            {'alert_id': alert.id, 'decision': 'confirmed', 'decided_at': '2026-10-17T01:00:00Z'},
            {'alert_id': alert.id, 'decision': 'dismissed', 'decided_at': '2026-10-17T03:00:00Z'}])

    def test_decide_unknown_and_invalid(self):
        self.assertIsNone(self.store.decide('missing', 'unclear', '2026-10-17T01:00:00Z'))
        self.assertEqual(self.store.decisions('missing'), [])
        self.store.add(make_alert(1))
        with self.assertRaises(ValueError):
            self.store.decide(make_alert(1).id, 'approved', '2026-10-17T01:00:00Z')
        self.assertEqual(self.store.get(make_alert(1).id).status, 'open')

    def test_update_replaces_evidence_but_keeps_decision(self):
        alert = make_alert(1)
        self.store.add(alert)
        self.store.decide(alert.id, 'unclear', '2026-10-17T01:00:00Z')
        ready = alert.model_copy(update={'evidence_status': 'ready',
                                         'evidence_image_url': '/evidence/a.jpg'})
        stored = self.store.update(ready)
        self.assertEqual((stored.evidence_status, stored.evidence_image_url), ('ready', '/evidence/a.jpg'))
        self.assertEqual((stored.status, stored.decision), ('reviewed', 'unclear'))
        self.assertEqual(self.store.get(alert.id), stored)
        self.assertEqual(self.store.list(status='reviewed')[1], 1)
        self.assertIsNone(self.store.update(make_alert(2)))
        self.assertIsNone(self.store.get(make_alert(2).id))

    def test_concurrent_adds_from_threads(self):
        alerts = [make_alert(n % 60, camera_id=f'cam_{n // 60}') for n in range(180)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(self.store.add, alerts + alerts))
        self.assertEqual(sum(results), 180)
        self.assertEqual(self.store.list()[1], 180)

    def test_file_backed_store_persists(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'nested' / 'alerts.db'
            store = AlertStore(path)
            store.add(make_alert(1))
            store.decide(make_alert(1).id, 'confirmed', '2026-10-17T01:00:00Z')
            mode = store._conn.execute('PRAGMA journal_mode').fetchone()[0]
            store.close()
            self.assertEqual(mode, 'wal')
            reopened = AlertStore(path)
            self.assertEqual(reopened.get(make_alert(1).id).decision, 'confirmed')
            self.assertEqual(len(reopened.decisions(make_alert(1).id)), 1)
            reopened.close()


if __name__ == '__main__':
    unittest.main()
