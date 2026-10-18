from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from app.models import Rule, Verdict, Zone
from engine.clip_replay import replay_clip
from engine.demo_recording import write_demo
from engine.evidence import EvidenceWriter
from engine.replay import read_frames
from engine.verification import StubVerifier, VerificationScheduler


class RecordedDemoTests(unittest.TestCase):
    def test_generated_demo_replays_compliant_violation_and_temporal_paths(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_demo(root)
            config = json.loads((root / 'config.json').read_text())
            zones = [Zone.model_validate(item) for item in config['zones']]
            rules = [Rule.model_validate(item) for item in config['rules']]
            cases = [('exit', False, True, 1), ('entrance', True, False, 0),
                     ('entrance', False, True, 2)]
            for index, (name, clear, professional, expected) in enumerate(cases):
                with self.subTest(name=name, clear=clear, professional=professional):
                    stub = StubVerifier({
                        'transparent_bag': Verdict(answer=clear, confidence=0.9, reason='STUB'),
                        'professional_camera': Verdict(answer=professional, confidence=0.9, reason='STUB'),
                    })
                    with VerificationScheduler(stub) as scheduler, EvidenceWriter(root / str(index)) as writer:
                        alerts = replay_clip(root / f'{name}.mp4', read_frames(root / f'{name}.tracks.jsonl'),
                            zones=zones, rules=rules, scheduler=scheduler, evidence_writer=writer)
                    self.assertEqual(len(alerts), expected)
                    for alert in alerts:
                        self.assertEqual(alert.evidence_status, 'ready')
                        self.assertTrue((root / str(index) / Path(alert.evidence_image_url).name).is_file())
                        self.assertTrue((root / str(index) / Path(alert.evidence_clip_url).name).is_file())
