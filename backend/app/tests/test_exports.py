import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.export_contracts import export
from app.models import Alert, Camera, CompileResult, RuleState, TrackFrame, Verdict, Zone


class ExportTests(unittest.TestCase):
    def test_exported_payloads_validate_and_are_reproducible(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            export(root)
            original = {path.name: path.read_bytes() for path in root.iterdir()}
            data = json.loads((root / 'examples.json').read_text())
            for camera in data['cameras']:
                Camera.model_validate(camera)
            for zone in data['zones']:
                Zone.model_validate(zone)
            CompileResult.model_validate(data['compile_result'])
            TrackFrame.model_validate(data['track_frame'])
            RuleState.model_validate(data['rule_state'])
            Alert.model_validate(data['alert'])
            Verdict.model_validate(data['verdict'])
            self.assertEqual(data['ws_alert']['data'], data['alert'])
            export(root)
            self.assertEqual(original, {path.name: path.read_bytes() for path in root.iterdir()})
