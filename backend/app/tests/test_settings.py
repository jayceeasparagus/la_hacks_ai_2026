"""Persisted configuration: round trips, validation and atomic writes."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from app.demo import demo_cameras, demo_rules, demo_zones
from app.models import Camera, Zone
from app.settings import Settings, SettingsError


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name) / 'data'
        self.settings = Settings(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def seed(self):
        self.settings.save_cameras(demo_cameras())
        self.settings.save_zones(demo_zones())
        self.settings.save_rules(demo_rules())

    def test_missing_files_are_empty(self):
        self.assertTrue(self.root.is_dir())
        self.assertEqual((self.settings.cameras(), self.settings.zones(), self.settings.rules()),
                         ([], [], []))

    def test_round_trips_match_api_bodies(self):
        self.seed()
        self.assertEqual(self.settings.cameras(), demo_cameras())
        self.assertEqual(self.settings.zones(), demo_zones())
        self.assertEqual(self.settings.rules(), demo_rules())
        reopened = Settings(self.root)
        self.assertEqual(reopened.rules(), demo_rules())
        for key, name in [('cameras', 'cameras.json'), ('zones', 'zones.json'), ('rules', 'policy.json')]:
            data = json.loads((self.root / name).read_text(encoding='utf-8'))
            self.assertEqual(list(data), [key])
        self.assertEqual(json.loads((self.root / 'zones.json').read_text())['zones'][0]['polygon'][0],
                         [0.2, 0.2])

    def test_dicts_are_accepted(self):
        saved = self.settings.save_cameras([{'id': 'cam_a', 'name': 'A', 'source': 'webcam:0'}])
        self.assertEqual(saved, [Camera(id='cam_a', name='A', source='webcam:0')])

    def test_camera_limits(self):
        four = [Camera(id=f'cam_{i}', name='Cam', source=f'webcam:{i}') for i in range(4)]
        for cameras in [four, [four[0], four[0]]]:
            with self.subTest(count=len(cameras)), self.assertRaises(SettingsError):
                self.settings.save_cameras(cameras)
        with self.assertRaises(SettingsError):
            self.settings.save_cameras([{'id': 'cam_a', 'name': 'A', 'source': 'x', 'url': 'y'}])
        self.assertFalse((self.root / 'cameras.json').exists())

    def test_zone_validation(self):
        self.settings.save_cameras(demo_cameras())
        good = demo_zones()
        bowtie = Zone(id='bad', camera_id='cam_exit', name='Bad',
                      polygon=[(0.1, 0.1), (0.9, 0.9), (0.9, 0.1), (0.1, 0.9)])
        unknown = good[0].model_copy(update={'camera_id': 'cam_missing'})
        for zones in [[good[0], good[0]], [good[0], bowtie], [unknown]]:
            with self.subTest(zones=[zone.id for zone in zones]), self.assertRaises(SettingsError):
                self.settings.save_zones(zones)
        self.assertFalse((self.root / 'zones.json').exists())

    def test_rule_validation(self):
        self.settings.save_cameras(demo_cameras())
        self.settings.save_zones(demo_zones())
        rules = demo_rules()
        unknown = rules[0].model_copy(update={'zone': 'nowhere'})
        for bad in [[rules[0], rules[0]], [unknown]]:
            with self.subTest(rules=[rule.id for rule in bad]), self.assertRaises(SettingsError):
                self.settings.save_rules(bad)
        self.assertEqual(self.settings.rules(), [])

    def test_referenced_cameras_and_zones_cannot_be_removed(self):
        self.seed()
        with self.assertRaisesRegex(SettingsError, 'cam_exit'):
            self.settings.save_cameras(demo_cameras()[:1])
        with self.assertRaisesRegex(SettingsError, 'emergency_exit'):
            self.settings.save_zones(demo_zones()[:1])
        self.assertEqual(self.settings.cameras(), demo_cameras())
        self.assertEqual(self.settings.zones(), demo_zones())
        # After the policy stops using the zone, it (and then its camera) can go.
        self.settings.save_rules(demo_rules()[:2])
        self.settings.save_zones(demo_zones()[:1])
        self.settings.save_cameras(demo_cameras()[:1])
        self.assertEqual([camera.id for camera in self.settings.cameras()], ['cam_entrance'])

    def test_failed_write_leaves_previous_file_intact(self):
        self.seed()
        before = (self.root / 'policy.json').read_bytes()
        with mock.patch('app.settings.os.replace', side_effect=OSError('disk full')), \
                self.assertRaises(OSError):
            self.settings.save_rules(demo_rules()[:1])
        self.assertEqual((self.root / 'policy.json').read_bytes(), before)
        self.assertEqual(sorted(path.name for path in self.root.iterdir()),
                         ['cameras.json', 'policy.json', 'zones.json'])

    def test_corrupt_file_raises_settings_error(self):
        (self.root / 'cameras.json').write_text('{"cameras": [', encoding='utf-8')
        with self.assertRaises(SettingsError):
            self.settings.cameras()

    def test_seed_demo_only_fills_missing_files(self):
        self.settings.save_cameras(demo_cameras() + [Camera(id='cam_x', name='X', source='webcam:2')])
        self.settings.seed_demo()
        self.assertEqual(len(self.settings.cameras()), 3)
        self.assertEqual(self.settings.zones(), demo_zones())
        self.assertEqual(self.settings.rules(), demo_rules())
        self.settings.save_rules([])
        self.settings.seed_demo()
        self.assertEqual(self.settings.rules(), [])

    def test_seed_demo_from_empty_directory(self):
        self.settings.seed_demo()
        self.assertEqual(self.settings.cameras(), demo_cameras())
        self.assertEqual(self.settings.rules(), demo_rules())


if __name__ == '__main__':
    unittest.main()
