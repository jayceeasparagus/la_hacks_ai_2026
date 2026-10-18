from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.seed_demo import seed_demo
from app.pipelines import FakePipeline


class DemoSeedTests(unittest.TestCase):
    def test_seed_is_playable_and_never_overwrites_existing_configuration(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = seed_demo(root)
            self.assertEqual(len(config.cameras), 2)
            self.assertEqual(len(config.rules), 3)
            pipe = FakePipeline(config.cameras[0], realtime=False)
            frames = pipe.frames()
            self.assertEqual(next(frames)[1].camera_id, 'cam_entrance')
            pipe.stop(); frames.close()
            original = (root / 'config.json').read_bytes()
            with self.assertRaises(FileExistsError):
                seed_demo(root)
            self.assertEqual((root / 'config.json').read_bytes(), original)
