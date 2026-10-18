"""Replay recorded video plus approved TrackFrame JSONL through all Part A stages."""

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

import cv2

from app.models import Rule, Verdict, Zone
from engine.engine import RuleEngine
from engine.evidence import EvidenceWriter
from engine.fake_tracks import synthetic_config
from engine.replay import read_frames
from engine.verification import StubVerifier, VerificationScheduler


def replay_clip(video_path, frames, *, zones=None, rules=None,
                scheduler=None, evidence_writer=None, on_alert=None):
    """Use existing tracks, not a detector. Caller owns shared worker lifetimes."""
    if (zones is None) != (rules is None):
        raise ValueError('Provide both zones and rules, or neither')
    capture = cv2.VideoCapture(str(video_path))
    engine, alerts = None, {}
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not capture.isOpened() or fps <= 0:
            raise ValueError('Video unavailable or missing frame rate')
        for tf in frames:
            if engine is None:
                configured_zones, configured_rules = synthetic_config(tf.camera_id) if zones is None else (zones, rules)
                engine = RuleEngine(tf.camera_id, configured_zones, configured_rules,
                    scheduler=scheduler, evidence_writer=evidence_writer, session_id='recorded-replay')
            if tf.camera_id != engine.camera_id:
                raise ValueError('A recorded replay supports one camera per video')
            frame_number = round(tf.ts * fps)
            if round(capture.get(cv2.CAP_PROP_POS_FRAMES)) != frame_number:
                capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            ok, image = capture.read()
            if not ok:
                raise ValueError(f'Video has no frame at source timestamp {tf.ts}')
            created_at = (datetime(1970, 1, 1, tzinfo=timezone.utc)
                          + timedelta(seconds=tf.ts)).isoformat().replace('+00:00', 'Z')
            engine.clock = lambda value=created_at: value
            for alert in engine.update(image, tf)[1]:
                alerts[alert.id] = alert
                if on_alert is not None:
                    on_alert(alert)
            for result in engine.poll_evidence():
                alerts[result.alert_id] = result.apply(alerts[result.alert_id])
        if engine is not None:
            for alert in engine.drain_verifications():
                alerts[alert.id] = alert
                if on_alert is not None:
                    on_alert(alert)
            for result in engine.drain_evidence():
                alerts[result.alert_id] = result.apply(alerts[result.alert_id])
        return list(alerts.values())
    except Exception:
        if engine is not None:
            engine.reset()  # invalidate verifier responses from a failed replay
        raise
    finally:
        capture.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', type=Path)
    parser.add_argument('tracks', type=Path)
    parser.add_argument('--config', type=Path, help='JSON object with zones and rules arrays')
    parser.add_argument('--evidence', type=Path, required=True, help='Directory for encoded evidence')
    parser.add_argument('--verifier', choices=['stub', 'person2'], default='stub')
    parser.add_argument('--stub-bag', choices=['clear', 'opaque', 'unclear'], default='unclear')
    parser.add_argument('--stub-camera', choices=['professional', 'ordinary', 'unclear'], default='unclear')
    args = parser.parse_args()
    try:
        config = {}
        if args.config:
            data = json.loads(args.config.read_text(encoding='utf-8'))
            config = {'zones': [Zone.model_validate(item) for item in data['zones']],
                      'rules': [Rule.model_validate(item) for item in data['rules']]}
        if args.verifier == 'person2':
            from verify.verifier import verify_crop
            provider = verify_crop
            print('Using Person 2 verifier; provider credentials/configuration apply.', file=sys.stderr)
        else:
            provider = StubVerifier({
                'transparent_bag': Verdict(answer={'clear': True, 'opaque': False}.get(args.stub_bag),
                    confidence=0.9 if args.stub_bag != 'unclear' else 0,
                    reason=f'STUB canned bag result: {args.stub_bag}'),
                'professional_camera': Verdict(
                    answer={'professional': True, 'ordinary': False}.get(args.stub_camera),
                    confidence=0.9 if args.stub_camera != 'unclear' else 0,
                    reason=f'STUB canned camera result: {args.stub_camera}'),
            })
            print('STUB MODE: canned answers, not visual classification.', file=sys.stderr)
        with VerificationScheduler(provider) as scheduler, EvidenceWriter(args.evidence) as writer:
            alerts = replay_clip(args.video, read_frames(args.tracks), scheduler=scheduler,
                                  evidence_writer=writer, **config)
        for alert in alerts:
            print(alert.model_dump_json())
        print(f'{len(alerts)} alert(s); existing tracks replayed; no detector evaluation.', file=sys.stderr)
    except (ValueError, KeyError, OSError, ImportError, TimeoutError) as exc:
        parser.exit(2, f'Recorded replay failed: {exc}\n')


if __name__ == '__main__':
    main()
