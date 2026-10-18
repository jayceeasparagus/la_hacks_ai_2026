"""Demo scenes and tracks replayed over real video, with a tiny generated clip."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import cv2
import numpy as np

from app.evidence import MIN_EVIDENCE_WIDTH, annotate_alert
from app.models import Camera
from app.scenes import load_scene, read_scene
from app.settings import Settings
from app.sources import VideoReplaySource, build_source
from engine.fake_tracks import scenario

ROOT = Path(__file__).resolve().parents[3]


def write_clip(path: Path, frames: int = 30, fps: float = 10.0, size=(160, 120)) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), fps, size)
    for index in range(frames):
        image = np.full((size[1], size[0], 3), index * 8 % 256, np.uint8)  # brightness encodes the frame
        writer.write(image)
    writer.release()


def write_tracks(path: Path, frames: int = 30, fps: float = 10.0) -> None:
    track = {'track_id': 1, 'object_class': 'backpack', 'bbox': [0.3, 0.3, 0.5, 0.7], 'confidence': 1.0}
    path.write_text(''.join(json.dumps({'camera_id': 'cam_x', 'ts': round(i / fps, 3), 'tracks': [track]}) + '\n'
                            for i in range(frames)), encoding='utf-8')


class VideoReplayTests(unittest.TestCase):
    def test_tracks_play_over_the_matching_video_frames(self):
        with TemporaryDirectory() as tmp:
            clip, tracks = Path(tmp) / 'clip.avi', Path(tmp) / 'clip.tracks.jsonl'
            write_clip(clip)
            write_tracks(tracks)
            source = build_source(Camera(id='cam_x', name='X', source=f'replay:{tracks}@{clip}'))
            self.assertIsInstance(source, VideoReplaySource)
            source._speed = 1000  # play instantly
            seen = [(image, tf) for image, tf in source.frames()]
            self.assertEqual(len(seen), 30)
            self.assertEqual(seen[0][0].shape, (120, 160, 3))  # real video frames, not rendered ones
            # frame k has brightness 8k (MJPG is lossy, so allow a small error)
            for k in (0, 10, 25):
                self.assertAlmostEqual(float(seen[k][0].mean()), k * 8, delta=4)
            self.assertTrue(source.ended)
            recent = source.recent_frames(1.0)
            self.assertGreaterEqual(len(recent), 10)
            self.assertEqual(recent[-1][1].shape, (120, 160, 3))
            self.assertEqual(source.first_frame().shape, (120, 160, 3))

    def test_missing_video_is_a_source_error(self):
        with TemporaryDirectory() as tmp:
            tracks = Path(tmp) / 'clip.tracks.jsonl'
            write_tracks(tracks)
            from app.sources import SourceError
            with self.assertRaises(SourceError):
                build_source(Camera(id='cam_x', name='X', source=f'replay:{tracks}@{Path(tmp) / "nope.mp4"}'))


class SceneTests(unittest.TestCase):
    def test_load_scene_resolves_paths_and_replaces_settings(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'scenes'
            folder.mkdir()
            scene = {
                'name': 'tiny', 'policy': 'Keep the exit clear for 5 seconds.',
                'cameras': [{'id': 'cam_x', 'name': 'X', 'source': 'replay:../clip.tracks.jsonl@../clip.avi'},
                            {'id': 'cam_y', 'name': 'Y', 'source': 'synthetic:exit_bag'}],
                'zones': [{'id': 'exit', 'camera_id': 'cam_x', 'name': 'Exit',
                           'polygon': [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]}],
                'rules': [{'id': 'blocked_exit', 'name': 'Exit obstruction', 'type': 'persistent_object',
                           'objects': ['backpack'], 'zone': 'exit', 'duration_seconds': 5, 'severity': 'urgent'}],
            }
            (folder / 'tiny.json').write_text(json.dumps(scene), encoding='utf-8')
            settings = Settings(Path(tmp) / 'settings')
            settings.seed_demo()  # something to replace
            loaded = load_scene(folder / 'tiny.json', settings)
            source = settings.cameras()[0].source
            self.assertEqual(source, f'replay:{(Path(tmp) / "clip.tracks.jsonl").resolve()}@{(Path(tmp) / "clip.avi").resolve()}')
            self.assertEqual(settings.cameras()[1].source, 'synthetic:exit_bag')
            self.assertEqual([r.id for r in settings.rules()], ['blocked_exit'])
            self.assertEqual([z.id for z in settings.zones()], ['exit'])
            self.assertEqual(loaded.name, 'tiny')

    def test_shipped_scenes_are_valid(self):
        scenes = sorted((ROOT / 'demo' / 'scenes').glob('*.json'))
        self.assertTrue(scenes)
        for path in scenes:
            with self.subTest(scene=path.name):
                scene = read_scene(path)
                zone_ids = {z.id for z in scene.zones}
                camera_ids = {c.id for c in scene.cameras}
                self.assertLessEqual(len(scene.cameras), 3)
                self.assertTrue(all(z.camera_id in camera_ids for z in scene.zones))
                self.assertTrue(all(r.zone in zone_ids for r in scene.rules))
                self.assertTrue(scene.policy and scene.credits)


class EvidenceSizeTests(unittest.TestCase):
    def test_small_frames_are_upscaled_for_readable_labels(self):
        from app.models import Alert
        from app.demo import demo_rules
        rule = demo_rules()[2]
        alert = Alert(id='a', incident_id='i', camera_id='cam_x', rule_id=rule.id, rule_name=rule.name,
                      zone_id=rule.zone, track_id=4, object_class='backpack', bbox=(0.8, 0.4, 0.85, 0.45),
                      ts=1.0, created_at='2026-10-17T00:00:00Z', elapsed_seconds=5.0, severity='urgent',
                      title='Possible exit obstruction', observation='x', confidence=1.0, rule_snapshot=rule)
        out = annotate_alert(np.zeros((288, 384, 3), np.uint8), alert)
        self.assertEqual(out.shape[1], MIN_EVIDENCE_WIDTH)
        # the object itself stays visible: the centre of its box is not covered by a label
        h, w = out.shape[:2]
        self.assertEqual(int(out[int(0.425 * h), int(0.825 * w)].sum()), 0)


if __name__ == '__main__':
    unittest.main()
