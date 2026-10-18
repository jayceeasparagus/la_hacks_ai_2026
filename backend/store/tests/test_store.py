from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.demo import demo_cameras, demo_rules, demo_zones
from engine.evidence import EvidenceResult
from engine.tests.test_evidence import example_alert
from store.config import ConfigurationStore, DuplicateConfiguration
from store.db import AlertStore


class StoreTests(unittest.TestCase):
    def test_persistence_dedup_and_decision_audit(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'alerts.sqlite3'
            store = AlertStore(path)
            alert = example_alert()
            self.assertTrue(store.save(alert))
            self.assertFalse(store.save(alert))
            store.decide(alert.id, 'confirmed')
            store.decide(alert.id, 'confirmed')
            store.decide(alert.id, 'dismissed')
            other = AlertStore(path)
            self.assertEqual(other.get(alert.id).decision, 'dismissed')
            self.assertEqual(len(other.decision_history(alert.id)), 2)
            with self.assertRaises(KeyError):
                store.get('missing')

    def test_concurrent_evidence_and_decision_do_not_overwrite_review(self):
        with TemporaryDirectory() as directory:
            store = AlertStore(Path(directory) / 'alerts.sqlite3')
            alert = example_alert()
            store.save(alert)
            result = EvidenceResult(alert.id, alert.camera_id, 'ready', '/evidence/test.jpg')
            with ThreadPoolExecutor(max_workers=2) as pool:
                a = pool.submit(store.decide, alert.id, 'dismissed')
                b = pool.submit(store.apply_evidence, result)
                a.result(); b.result()
            final = store.get(alert.id)
            self.assertEqual(final.decision, 'dismissed')
            self.assertEqual(final.evidence_status, 'ready')

    def test_filtering_pagination_and_urgent_order(self):
        with TemporaryDirectory() as directory:
            store = AlertStore(Path(directory) / 'db')
            urgent = example_alert()
            newer = urgent.model_copy(update={'id': 'newer', 'severity': 'review',
                'camera_id': 'other', 'created_at': '2026-10-17T01:00:00Z'})
            store.save(urgent); store.save(newer)
            alerts, total = store.list(limit=1)
            self.assertEqual((alerts[0].id, total), (urgent.id, 2))
            self.assertEqual(store.list(camera_id='other')[1], 1)
            store.decide(urgent.id, 'unclear')
            self.assertEqual(store.list(status='reviewed')[1], 1)

    def test_configuration_roundtrip_and_reference_validation(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            store = ConfigurationStore(path)
            config = store.replace(cameras=demo_cameras(), zones=demo_zones(), rules=demo_rules())
            self.assertEqual(ConfigurationStore(path).snapshot(), config)
            with self.assertRaises(ValueError):
                store.replace(cameras=[])
            self.assertEqual(store.snapshot(), config)
            with self.assertRaises(DuplicateConfiguration):
                store.replace(cameras=[demo_cameras()[0]] * 2)

    def test_failed_configuration_write_preserves_previous_state(self):
        with TemporaryDirectory() as directory:
            store = ConfigurationStore(Path(directory) / 'config.json')
            before = store.replace(cameras=demo_cameras())
            with patch('store.config.os.replace', side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):
                    store.replace(zones=demo_zones())
            self.assertEqual(store.snapshot(), before)
            self.assertEqual(ConfigurationStore(store.path).snapshot(), before)

    def test_four_cameras_and_invalid_polygon_are_rejected(self):
        with TemporaryDirectory() as directory:
            store = ConfigurationStore(Path(directory) / 'config.json')
            with self.assertRaises(ValueError):
                store.replace(cameras=[demo_cameras()[0].model_copy(update={'id': str(i)}) for i in range(4)])
            store.replace(cameras=demo_cameras())
            zone = demo_zones()[0].model_copy(update={'polygon': [(0,0), (1,1), (1,0), (0,1)]})
            with self.assertRaises(ValueError):
                store.replace(zones=[zone])
