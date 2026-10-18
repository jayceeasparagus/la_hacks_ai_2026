"""Person 1's draft TrackFrames become approved, monotonic engine input."""

from dataclasses import dataclass, field
import unittest

from app.adapter import ContractAdapter
from app.models import Track, TrackFrame


# Copies of Person 1's vision/trackframe.py dataclasses; app/ must not import vision/.
@dataclass
class DraftTrack:
    track_id: int
    class_name: str
    conf: float
    bbox: list[float]


@dataclass
class DraftFrame:
    camera_id: str
    frame_index: int
    ts: float
    width: int
    height: int
    tracks: list[DraftTrack] = field(default_factory=list)


def draft(ts, tracks=(), camera='cam_exit', frame_index=0):
    return DraftFrame(camera_id=camera, frame_index=frame_index, ts=ts, width=960, height=540,
                      tracks=list(tracks))


def raw(track_id=7, class_name='backpack', conf=0.61, bbox=(0.41, 0.55, 0.52, 0.80)):
    return DraftTrack(track_id=track_id, class_name=class_name, conf=conf, bbox=list(bbox))


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.adapter = ContractAdapter('cam_exit')

    def test_field_mapping_and_rebased_time(self):
        frame, restarted = self.adapter.convert(draft(1_760_000_000.25, [raw()]))
        self.assertTrue(restarted)
        self.assertIsInstance(frame, TrackFrame)
        self.assertEqual(frame.ts, 0)
        self.assertEqual(frame.tracks, [Track(track_id=7, object_class='backpack',
                                              bbox=(0.41, 0.55, 0.52, 0.80), confidence=0.61)])
        frame, restarted = self.adapter.convert(draft(1_760_000_000.75, [raw()]))
        self.assertFalse(restarted)
        self.assertAlmostEqual(frame.ts, 0.5)

    def test_dict_input_matches_dataclass(self):
        data = {'camera_id': 'cam_exit', 'frame_index': 0, 'ts': 2.0, 'width': 960, 'height': 540,
                'tracks': [{'track_id': 3, 'class_name': 'chair', 'conf': 0.8,
                            'bbox': [0.1, 0.2, 0.3, 0.4]}]}
        frame, restarted = self.adapter.convert(data)
        self.assertTrue(restarted)
        self.assertEqual(frame.tracks[0].object_class, 'chair')
        self.assertEqual(frame.tracks[0].bbox, (0.1, 0.2, 0.3, 0.4))

    def test_bbox_and_confidence_are_clamped(self):
        frame, _ = self.adapter.convert(draft(0, [raw(bbox=(-0.1, 0.2, 1.3, 1.0), conf=1.2),
                                                  raw(track_id=8, conf=-0.1)]))
        self.assertEqual(frame.tracks[0].bbox, (0.0, 0.2, 1.0, 1.0))
        self.assertEqual(frame.tracks[0].confidence, 1.0)
        self.assertEqual(frame.tracks[1].confidence, 0.0)

    def test_bad_tracks_are_dropped_without_raising(self):
        bad = [raw(track_id=1, bbox=(0.5, 0.2, 0.5, 0.6)),        # zero width
               raw(track_id=2, bbox=(0.6, 0.2, 0.4, 0.6)),        # inverted
               raw(track_id=3, bbox=(1.2, 0.2, 1.5, 0.6)),        # collapses after clamping
               raw(track_id=4, bbox=(0.1, float('nan'), 0.3, 0.6)),
               raw(track_id=5, conf=float('inf')),
               raw(track_id=6, class_name='knife'),
               raw(track_id=-1),
               raw(track_id=True),
               raw(track_id=9, bbox=(0.1, 0.2, 0.3)),
               {'track_id': 10, 'class_name': 'chair'},
               None,
               raw(track_id=11)]
        frame, _ = self.adapter.convert(draft(0, bad))
        self.assertEqual([track.track_id for track in frame.tracks], [11])

    def test_duplicate_track_ids_keep_highest_confidence(self):
        frame, _ = self.adapter.convert(draft(0, [raw(conf=0.4), raw(conf=0.9, bbox=(0.1, 0.1, 0.2, 0.2)),
                                                  raw(conf=0.5)]))
        self.assertEqual(len(frame.tracks), 1)
        self.assertEqual(frame.tracks[0].confidence, 0.9)
        self.assertEqual(frame.tracks[0].bbox, (0.1, 0.1, 0.2, 0.2))

    def test_non_increasing_time_is_skipped(self):
        self.adapter.convert(draft(10.0))
        self.adapter.convert(draft(10.4))
        self.assertEqual(self.adapter.convert(draft(10.4)), (None, False))
        self.assertEqual(self.adapter.convert(draft(9.9)), (None, False))   # back exactly 0.5 s
        frame, restarted = self.adapter.convert(draft(10.5))
        self.assertFalse(restarted)
        self.assertAlmostEqual(frame.ts, 0.5)

    def test_backward_jump_restarts_the_session(self):
        self.adapter.convert(draft(5.0))
        self.adapter.convert(draft(8.0))
        frame, restarted = self.adapter.convert(draft(0.2))
        self.assertTrue(restarted)
        self.assertEqual(frame.ts, 0)
        frame, restarted = self.adapter.convert(draft(0.3))
        self.assertFalse(restarted)
        self.assertAlmostEqual(frame.ts, 0.1)

    def test_reset_starts_a_new_session(self):
        self.adapter.convert(draft(5.0))
        self.adapter.reset()
        frame, restarted = self.adapter.convert(draft(6.0))
        self.assertTrue(restarted)
        self.assertEqual(frame.ts, 0)

    def test_non_finite_time_is_skipped(self):
        self.assertEqual(self.adapter.convert(draft(float('nan'))), (None, False))
        self.assertTrue(self.adapter.convert(draft(1.0))[1])

    def test_approved_frame_passes_through(self):
        approved = TrackFrame(camera_id='cam_exit', ts=0, tracks=[
            Track(track_id=1, object_class='suitcase', bbox=(0.2, 0.2, 0.4, 0.7), confidence=0.95)])
        frame, restarted = self.adapter.convert(approved)
        self.assertTrue(restarted)
        self.assertEqual(frame, approved)
        later = approved.model_copy(update={'ts': 1.5})
        self.assertEqual(self.adapter.convert(later), (later, False))

    def test_camera_mismatch_raises(self):
        with self.assertRaises(ValueError):
            self.adapter.convert(draft(0, camera='cam_entrance'))


if __name__ == '__main__':
    unittest.main()
