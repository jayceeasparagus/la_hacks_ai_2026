from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from app.demo import demo_rules
from app.models import Track
from engine.alerts import obstruction_alert
from engine.evidence import EvidenceWriter, FrameBuffer


def example_alert():
    return obstruction_alert(incident_id='example', camera_id='cam_exit', rule=demo_rules()[2],
        track=Track(track_id=1, object_class='backpack', bbox=(0.3, 0.3, 0.5, 0.7), confidence=0.9),
        ts=5, elapsed=5, confidence=0.9, zone_name='Emergency exit',
        created_at='2026-10-17T00:00:00Z')


class EvidenceTests(unittest.TestCase):
    def test_ring_owns_frames_and_obeys_time_byte_and_sampling_limits(self):
        buffer = FrameBuffer(max_bytes=3 * 100 * 120 * 3, max_width=120)
        image = np.full((100, 120, 3), 150, np.uint8)
        buffer.remember(image, 0)
        image[:] = 0
        self.assertEqual(buffer.snapshot(0)[0][1].mean(), 150)
        buffer.remember(image, 0.01)
        self.assertEqual(len(buffer.snapshot(0.01)), 1)
        for tick in range(1, 100):
            buffer.remember(image, tick / 10)
        self.assertLessEqual(buffer.byte_size, buffer.max_bytes)
        self.assertLessEqual(len(buffer.snapshot(9.9)), 3)
        self.assertFalse(buffer.snapshot(9.9)[0][1].flags.writeable)
        buffer.clear()
        self.assertEqual(buffer.snapshot(10), [])

    def test_real_jpeg_and_four_second_mp4_are_decodable(self):
        with TemporaryDirectory() as directory, EvidenceWriter(Path(directory)) as writer:
            buffer = FrameBuffer()
            for tick in range(51):
                buffer.remember(np.full((120, 160, 3), tick * 3, np.uint8), tick / 10)
            original = np.full((120, 160, 3), 120, np.uint8)
            ticket = writer.submit(example_alert(), original, buffer.snapshot(5), snapshot_ts=5)
            original[:] = 0
            result = ticket.future.result(timeout=5)
            self.assertEqual(result.status, 'ready')
            image = cv2.imread(str(Path(directory) / Path(result.image_url).name))
            self.assertEqual(image.shape, (120, 160, 3))
            # The object box is red; a capture-source mutation did not blank it.
            self.assertGreater(int(image[60, 48, 2]), int(image[60, 48, 0]) + 80)
            clip = cv2.VideoCapture(str(Path(directory) / Path(result.clip_url).name))
            try:
                self.assertTrue(clip.read()[0])
                duration = clip.get(cv2.CAP_PROP_FRAME_COUNT) / clip.get(cv2.CAP_PROP_FPS)
                self.assertAlmostEqual(duration, 4, delta=0.15)
            finally:
                clip.release()
            self.assertFalse(list(Path(directory).glob('*.part*')))

    def test_generated_filenames_do_not_use_alert_text(self):
        with TemporaryDirectory() as directory, EvidenceWriter(Path(directory)) as writer:
            alert = example_alert()
            alert.id = '../../outside'
            ticket = writer.submit(alert, np.zeros((120, 160, 3), np.uint8), [], snapshot_ts=5)
            result = ticket.future.result(timeout=5)
            self.assertEqual(result.status, 'ready')
            self.assertEqual(len(list(Path(directory).glob('*.jpg'))), 1)
            self.assertNotIn('outside', result.image_url)

    def test_evidence_merge_preserves_operator_decision(self):
        with TemporaryDirectory() as directory, EvidenceWriter(Path(directory)) as writer:
            alert = example_alert()
            ticket = writer.submit(alert, np.zeros((120, 160, 3), np.uint8), [], snapshot_ts=5)
            result = ticket.future.result(timeout=5)
            alert.status, alert.decision = 'reviewed', 'dismissed'
            alert.decided_at = '2026-10-17T00:00:01Z'
            updated = result.apply(alert)
            self.assertEqual(updated.decision, 'dismissed')
            self.assertEqual(updated.status, 'reviewed')
            self.assertEqual(updated.evidence_status, 'ready')
            with self.assertRaises(ValueError):
                result.apply(alert.model_copy(update={'camera_id': 'another'}))

    def test_video_failure_keeps_jpeg(self):
        with TemporaryDirectory() as directory, EvidenceWriter(Path(directory)) as writer:
            image = np.zeros((120, 160, 3), np.uint8)
            with patch.object(writer, '_write_clip', side_effect=RuntimeError('codec unavailable')):
                ticket = writer.submit(example_alert(), image, [(4, image), (5, image)], snapshot_ts=5)
                result = ticket.future.result(timeout=5)
            self.assertEqual(result.status, 'ready')
            self.assertIsNotNone(result.image_url)
            self.assertIsNone(result.clip_url)

    def test_jpeg_failure_reports_unavailable(self):
        with TemporaryDirectory() as directory, EvidenceWriter(Path(directory)) as writer:
            with patch('engine.evidence.cv2.imencode', return_value=(False, None)):
                ticket = writer.submit(example_alert(), np.zeros((120, 160, 3), np.uint8), [], snapshot_ts=5)
                self.assertEqual(ticket.future.result(timeout=5).status, 'unavailable')
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_slow_writer_is_bounded_and_nonblocking(self):
        release = threading.Event()
        with TemporaryDirectory() as directory, EvidenceWriter(Path(directory), max_pending=1) as writer:
            actual = writer._write
            def slow(*args):
                release.wait(2)
                return actual(*args)
            with patch.object(writer, '_write', side_effect=slow):
                image = np.zeros((120, 160, 3), np.uint8)
                started = time.monotonic()
                ticket = writer.submit(example_alert(), image, [], snapshot_ts=5)
                self.assertIsNone(writer.submit(example_alert(), image, [], snapshot_ts=5))
                self.assertLess(time.monotonic() - started, 0.1)
                self.assertIsNone(writer.poll(ticket))
                release.set()
                self.assertEqual(ticket.future.result(timeout=5).status, 'ready')

    def test_no_image_means_no_job(self):
        with TemporaryDirectory() as directory, EvidenceWriter(Path(directory)) as writer:
            self.assertIsNone(writer.submit(example_alert(), None, [], snapshot_ts=5))
