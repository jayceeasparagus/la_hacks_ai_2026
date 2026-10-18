from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.adapters import demo_compile, validate_compile_result
from app.demo import demo_cameras, demo_zones
from app.models import Camera
from app.pipelines import FakePipeline, VisionAdapter, adapt_track_frame
from engine.demo_recording import write_demo


class AdapterTests(unittest.TestCase):
    def test_person_one_shape_normalizes_without_changing_contract(self):
        raw = {'camera_id': 'other', 'ts': 100.5, 'width': 960, 'height': 540, 'frame_index': 5,
               'tracks': [{'track_id': 1, 'class_name': 'backpack', 'conf': 0.9,
                           'bbox': [0.2, 0.2, 0.4, 0.7]}]}
        tf = adapt_track_frame(raw, 'camera', origin=100)
        self.assertEqual(tf.ts, 0.5)
        self.assertEqual(tf.camera_id, 'camera')
        self.assertEqual(tf.tracks[0].object_class, 'backpack')

    def test_recorded_pipeline_binds_camera_and_stops(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_demo(root)
            pipe = FakePipeline(Camera(id='new_camera', name='Test', source=f'clip:{root / "exit.mp4"}'), realtime=False)
            stream = pipe.frames()
            image, frame = next(stream)
            self.assertEqual(frame.camera_id, 'new_camera')
            self.assertEqual(image.shape, (270, 480, 3))
            pipe.stop()
            self.assertEqual(list(stream), [])

    def test_demo_compile_and_unsupported_requests(self):
        prompt = 'Only clear bags at the main entrance. Professional cameras require review. Keep emergency exit clear.'
        result = demo_compile(prompt, demo_zones())
        self.assertEqual(len(result.rules), 3)
        self.assertIn('DEMO', result.warnings[0])
        validate_compile_result(result, demo_cameras(), demo_zones())
        self.assertTrue(demo_compile('Detect concealed items', demo_zones()).unsupported)

    def test_missing_zone_does_not_create_unbound_rule(self):
        self.assertFalse(demo_compile('Only clear bags', []).rules)

    def test_live_source_clock_resets_after_disconnect_without_index_rewind(self):
        class Inner:
            status = 'online'
            def __init__(self, *args, **kwargs): pass
            def frames(self):
                for index, ts in [(10,100), (11,110)]:
                    yield None, {'ts':ts,'frame_index':index,'tracks':[]}
            def stop(self): pass
        module = SimpleNamespace(VisionPipeline=Inner)
        with patch.dict('sys.modules', {'vision': SimpleNamespace(), 'vision.pipeline': module}):
            adapter = VisionAdapter(Camera(id='cam', name='Live', source='webcam:0'))
        frames = adapter.frames()
        self.assertEqual(next(frames)[1].ts, 0)
        adapter.reset_session()
        self.assertEqual(next(frames)[1].ts, 0)
