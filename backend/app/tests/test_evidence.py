"""Evidence images and clips are written in the background and served safely."""

from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest import mock

import cv2
import numpy as np

from app.evidence import EvidenceWriter, safe_name
from store.tests.test_db import make_alert


def image(value: int, size=(160, 120)) -> np.ndarray:
    return np.full((size[1], size[0], 3), value, np.uint8)


class Collector:
    def __init__(self):
        self.calls = []
        self.done = threading.Event()

    def __call__(self, alert):
        self.calls.append(alert)
        self.done.set()


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.writer = EvidenceWriter(self.root)
        self.alert = make_alert(1)

    def tearDown(self):
        self.writer.shutdown()
        self.temp.cleanup()

    def run_job(self, frame, recent):
        done = Collector()
        returned = self.writer.submit(self.alert, frame, recent, done)
        self.writer.shutdown(wait=True)
        self.assertTrue(done.done.is_set())
        self.assertEqual(len(done.calls), 1)
        return returned, done.calls[0]

    def test_safe_name_is_deterministic_and_unique(self):
        name = safe_name(self.alert.id)
        self.assertEqual(name, safe_name(self.alert.id))
        self.assertNotEqual(name, safe_name(self.alert.id + 'x'))
        self.assertNotEqual(safe_name('a:b'), safe_name('a/b'))
        for alert_id in ['../../etc/passwd', 'é', '', 'x' * 500]:
            self.assertRegex(safe_name(alert_id) + '.jpg', r'^[A-Za-z0-9_-]+\.jpg$')

    def test_without_frame_evidence_is_unavailable(self):
        done = Collector()
        returned = self.writer.submit(self.alert, None, [(0.0, image(10)), (0.1, image(20))], done)
        self.writer.shutdown()
        self.assertEqual(returned.evidence_status, 'unavailable')
        self.assertEqual(done.calls, [])

    def test_image_only(self):
        returned, ready = self.run_job(image(50), None)
        self.assertEqual(returned.evidence_status, 'pending')
        self.assertEqual(ready.evidence_status, 'ready')
        self.assertEqual(ready.id, self.alert.id)
        name = safe_name(self.alert.id)
        self.assertEqual(ready.evidence_image_url, f'/evidence/{name}.jpg')
        self.assertIsNone(ready.evidence_clip_url)
        path = self.writer.resolve(f'{name}.jpg')
        self.assertIsNotNone(path)
        written = cv2.imread(str(path))
        self.assertEqual(written.shape, (120, 160, 3))
        self.assertGreater(int(np.abs(written.astype(int) - 50).sum()), 0)   # box and label drawn
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), [f'{name}.jpg'])

    def test_clip_from_recent_frames(self):
        # 5 s of 10 fps frames; only the last 4 s go into the clip. One frame has another size.
        recent = [(100 + i / 10, image(i * 5)) for i in range(50)]
        recent[-3] = (recent[-3][0], image(200, size=(320, 240)))
        _, ready = self.run_job(image(50), recent)
        name = safe_name(self.alert.id)
        self.assertEqual(ready.evidence_status, 'ready')
        self.assertEqual(ready.evidence_clip_url, f'/evidence/{name}.mp4')
        clip = self.writer.resolve(f'{name}.mp4')
        self.assertIsNotNone(clip)
        self.assertIn(self.writer.codec, ('avc1', 'mp4v'))
        capture = cv2.VideoCapture(str(clip))
        try:
            self.assertTrue(capture.isOpened())
            self.assertAlmostEqual(capture.get(cv2.CAP_PROP_FPS), 10, delta=0.5)
            count, size = 0, None
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                count, size = count + 1, frame.shape[:2]
        finally:
            capture.release()
        self.assertGreaterEqual(count, 39)
        self.assertEqual(size, (120, 160))

    def test_single_recent_frame_gives_no_clip(self):
        _, ready = self.run_job(image(50), [(1.0, image(10))])
        self.assertEqual(ready.evidence_status, 'ready')
        self.assertIsNone(ready.evidence_clip_url)

    def test_failure_reports_unavailable(self):
        with mock.patch('app.evidence.cv2.imwrite', return_value=False),                 self.assertLogs('app.evidence', 'ERROR'):
            returned, failed = self.run_job(image(50), None)
        self.assertEqual(returned.evidence_status, 'pending')
        self.assertEqual(failed.evidence_status, 'unavailable')
        self.assertIsNone(failed.evidence_image_url)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_bad_frame_reports_unavailable(self):
        with self.assertLogs('app.evidence', 'ERROR'):
            _, failed = self.run_job(np.zeros((0,), np.uint8), None)
        self.assertEqual(failed.evidence_status, 'unavailable')

    def test_callback_errors_are_contained(self):
        calls = []

        def broken(alert):
            calls.append(alert)
            raise RuntimeError('socket closed')

        with self.assertLogs('app.evidence', 'ERROR'):
            self.writer.submit(self.alert, image(50), None, broken)
            self.writer.shutdown()
        self.assertEqual(len(calls), 1)

    def test_submit_after_shutdown_does_not_raise(self):
        self.writer.shutdown()
        done = Collector()
        with self.assertLogs('app.evidence', 'ERROR'):
            returned = self.writer.submit(self.alert, image(50), None, done)
        self.assertEqual(returned.evidence_status, 'unavailable')
        self.assertEqual(done.calls, [])

    def test_resolve_rejects_unsafe_and_unknown_names(self):
        (self.root / 'real.jpg').write_bytes(b'x')
        self.assertEqual(self.writer.resolve('real.jpg'), (self.root / 'real.jpg').resolve())
        for name in ['../x.jpg', 'a/b.jpg', 'a\\b.jpg', 'unknown.jpg', 'real.png', 'real.jpg\n',
                     '.jpg', 'real.tmp.jpg', '', None, 'C:x.jpg']:
            with self.subTest(name=name):
                self.assertIsNone(self.writer.resolve(name))


if __name__ == '__main__':
    unittest.main()
