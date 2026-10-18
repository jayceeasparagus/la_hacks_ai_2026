import threading
import time
import unittest

from app.models import Verdict
from engine.verification import StubVerifier, VerificationScheduler


def wait_for(scheduler, ticket, seconds=3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = scheduler.poll(ticket)
        if result is not None:
            return result
        time.sleep(0.002)
    raise AssertionError('Verification did not complete')


class VerificationTests(unittest.TestCase):
    def test_canned_verdict_and_cache_are_validated(self):
        stub = StubVerifier({'transparent_bag': Verdict(answer=False, confidence=0.9, reason='test')})
        with VerificationScheduler(stub) as scheduler:
            key = ('camera', 'session', 'transparent_bag', 1)
            ticket = scheduler.submit(key, object(), 'transparent_bag')
            self.assertFalse(wait_for(scheduler, ticket).answer)
            self.assertIs(ticket, scheduler.submit(key, object(), 'transparent_bag'))
            self.assertEqual(stub.calls, ['transparent_bag'])

    def test_rate_limit_is_shared_across_camera_keys(self):
        starts = []
        def provider(crop, check):
            starts.append(time.monotonic())
            return Verdict(answer=True, confidence=1, reason='test')
        with VerificationScheduler(provider, max_workers=3) as scheduler:
            tickets = [scheduler.submit((camera, 'session', 'transparent_bag', 1), None,
                                         'transparent_bag') for camera in ['a', 'b', 'c']]
            for ticket in tickets:
                wait_for(scheduler, ticket)
        self.assertEqual(len(starts), 3)
        self.assertTrue(all(b - a >= 0.49 for a, b in zip(starts, starts[1:])))

    def test_queue_is_bounded_and_submit_does_not_wait(self):
        release = threading.Event()
        def provider(crop, check):
            release.wait(2)
            return Verdict(answer=True, confidence=1, reason='test')
        with VerificationScheduler(provider, max_pending=1) as scheduler:
            ticket = scheduler.submit(('a', 's', 'x', 1), None, 'x')
            started = time.monotonic()
            self.assertIsNone(scheduler.submit(('b', 's', 'x', 2), None, 'x'))
            self.assertLess(time.monotonic() - started, 0.1)
            release.set()
            self.assertTrue(wait_for(scheduler, ticket).answer)

    def test_timeout_returns_unclear_and_late_answer_cannot_replace_it(self):
        release = threading.Event()
        def provider(crop, check):
            release.wait(2)
            return Verdict(answer=True, confidence=1, reason='late')
        with VerificationScheduler(provider, timeout_seconds=0.03) as scheduler:
            ticket = scheduler.submit(('a', 's', 'x', 1), None, 'x')
            self.assertIsNone(wait_for(scheduler, ticket).answer)
            release.set()
            ticket.future.result(timeout=1)
            self.assertIsNone(scheduler.poll(ticket).answer)

    def test_invalid_answer_retries_once_then_unclear(self):
        calls = []
        def provider(crop, check):
            calls.append(check)
            return {'answer': 'false', 'confidence': 0.9, 'reason': 'invalid boolean'}
        with VerificationScheduler(provider) as scheduler:
            ticket = scheduler.submit(('a', 's', 'x', 1), None, 'x')
            result = wait_for(scheduler, ticket)
            self.assertIsNone(result.answer)
            self.assertEqual(len(calls), 2)

    def test_provider_failure_becomes_manual_review(self):
        def provider(crop, check):
            raise RuntimeError('do not leak this')
        with VerificationScheduler(provider) as scheduler:
            ticket = scheduler.submit(('a', 's', 'x', 1), None, 'x')
            result = wait_for(scheduler, ticket)
            self.assertIsNone(result.answer)
            self.assertNotIn('do not leak', result.reason)

    def test_unknown_stub_is_explicitly_unclear(self):
        self.assertIsNone(StubVerifier()(None, 'transparent_bag').answer)
