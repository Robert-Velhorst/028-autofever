import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from backend.dispatch_lock import DeliveryBusy, delivery_lock
from backend.reconcile import main, load_decision
from backend.service import Conflict, Denied, Invalid, Store


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'state.sqlite3'
        self.key = bytes(range(32))
        self.clock = [1800000000]
        self.store = Store(self.path, self.key, clock=lambda: self.clock[0])
        self.owner = self.store.create_owner()
        self.plan = {'recipients': [{'id': 'alice', 'channel': 'email', 'destination': 'alice@example.invalid',
                                    'message': 'Private illness note'}], 'tasks': []}
        self.eid = self.store.activate(self.owner, 'one', self.plan, link_ttl=3600)
        self.job = self.jobs()[0]['id']

    def jobs(self):
        return self.store.episode(self.owner, self.eid)['notifications']

    def uncertain(self):
        def lost(_):
            raise TimeoutError('not retained')
        self.store.dispatch_one(lost)

    def decision(self, **changes):
        return {**dict(job_id=self.job, attempt=1, outcome='accepted', retry=False,
                       operator='private-test-operator', evidence_source='provider_record',
                       evidence_reference='private-test-confirmed-submission-123'), **changes}

    def test_dry_run_does_not_settle_or_write_audit(self):
        self.uncertain()
        before = self.store.review_job(self.job)
        self.assertFalse(self.store.reconcile_job(self.decision())['applied'])
        self.assertEqual(self.store.review_job(self.job), before)
        with self.assertRaises(Conflict): self.store.close(self.owner, self.eid, 'recovered', 'Better')

    def test_accepted_resolution_unlocks_recovery_and_is_durable_private_and_idempotent(self):
        self.uncertain()
        decision = self.decision()
        result = self.store.reconcile_job(decision, apply=True)
        self.assertEqual(result['result'], 'accepted')
        reopened = Store(self.path, self.key, clock=lambda: self.clock[0])
        self.assertTrue(reopened.reconcile_job(decision, apply=True)['replayed'])
        review = reopened.review_job(self.job)
        self.assertEqual(len(review['resolutions']), 1)
        self.assertEqual(review['status'], 'accepted')
        for private in ('private-test-operator', 'private-test-confirmed-submission-123', 'alice@example.invalid', 'Private illness note'):
            self.assertNotIn(private, json.dumps(review))
            self.assertNotIn(private.encode(), self.path.read_bytes())
        with reopened.transaction() as db:
            entry = db.execute("SELECT name,value FROM metadata WHERE name LIKE 'resolution:%'").fetchone()
            self.assertEqual(reopened.open(entry['name'], entry['value'])['decision'], decision)
        reopened.close(self.owner, self.eid, 'recovered', 'Better, thank you')
        self.assertEqual([j['kind'] for j in self.jobs()], ['illness', 'recovery'])

    def test_proven_nonacceptance_without_retry_allows_close_without_recovery_notice(self):
        self.uncertain()
        self.store.reconcile_job(self.decision(outcome='not_accepted'), apply=True)
        self.store.close(self.owner, self.eid, 'recovered', 'Better', recovery_recipients=[])
        self.assertEqual(len(self.jobs()), 1)
        self.assertEqual(self.jobs()[0]['status'], 'failed')

    def test_explicit_retry_keeps_same_job_and_cannot_be_reapplied_to_new_attempt(self):
        self.uncertain()
        decision = self.decision(outcome='not_accepted', retry=True)
        self.store.reconcile_job(decision, apply=True)
        self.assertFalse(self.store.dispatch_one(lambda _: self.fail('retry delay bypassed')))
        self.clock[0] += 30
        self.uncertain()
        self.assertEqual(self.jobs()[0]['attempts'], 2)
        self.assertTrue(self.store.reconcile_job(decision, apply=True)['replayed'])
        self.assertEqual(self.jobs()[0]['status'], 'uncertain')
        self.store.reconcile_job(self.decision(attempt=2), apply=True)
        self.assertEqual(len(self.store.review_job(self.job)['resolutions']), 2)

    def test_unknown_evidence_stale_attempt_and_changed_decision_fail_closed(self):
        self.uncertain()
        for changes in ({'outcome': 'unknown'}, {'retry': True}, {'evidence_source': 'inbox_absence'},
                        {'operator': ''}, {'evidence_reference': ''}, {'attempt': True},
                        {'retry': 1}, {'extra': 'ignored'}, {'evidence_reference': 'bad\nreference'}):
            with self.subTest(changes=changes), self.assertRaises(Invalid):
                self.store.reconcile_job(self.decision(**changes), apply=True)
        with self.assertRaises(Conflict): self.store.reconcile_job(self.decision(attempt=2), apply=True)
        with self.assertRaises(Denied): self.store.reconcile_job(self.decision(job_id='unknown'), apply=True)
        self.store.reconcile_job(self.decision(), apply=True)
        for changes in ({'outcome': 'not_accepted'}, {'evidence_reference': 'rewritten'}):
            with self.assertRaises(Conflict): self.store.reconcile_job(self.decision(**changes), apply=True)

    def test_queued_and_confirmed_jobs_cannot_be_overridden(self):
        with self.assertRaises(Conflict): self.store.reconcile_job(self.decision(), apply=True)
        self.store.dispatch_one(lambda _: 'accepted')
        with self.assertRaises(Conflict): self.store.reconcile_job(self.decision(outcome='not_accepted'), apply=True)

    def test_expired_link_and_attempt_limit_prevent_requeue(self):
        self.uncertain()
        self.clock[0] += 3601
        with self.assertRaises(Conflict): self.store.reconcile_job(self.decision(outcome='not_accepted', retry=True), apply=True)
        self.store.reconcile_job(self.decision(outcome='not_accepted'), apply=True)
        self.assertEqual(self.jobs()[0]['status'], 'failed')
        # Simulate an already exhausted durable job, not an external send.
        with self.store.transaction() as db:
            db.execute("UPDATE jobs SET status='uncertain',attempts=5 WHERE id=?", (self.job,))
        with self.assertRaises(Conflict): self.store.reconcile_job(self.decision(attempt=5, outcome='not_accepted', retry=True), apply=True)

    def test_active_sender_prevents_resolution_even_after_lease_quarantine(self):
        started, finish = threading.Event(), threading.Event()
        def delayed(_):
            started.set()
            if not finish.wait(5): raise AssertionError('test sender release missing')
            return 'late-accepted'
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(self.store.dispatch_one, delayed)
            try:
                self.assertTrue(started.wait(3))
                self.clock[0] += 301
                self.store.quarantine_expired()
                self.assertEqual(self.jobs()[0]['status'], 'uncertain')
                with self.assertRaises(DeliveryBusy):
                    self.store.reconcile_job(self.decision(outcome='not_accepted', retry=True), apply=True)
            finally:
                finish.set()
            self.assertTrue(pending.result(timeout=3))
        self.assertEqual(self.jobs()[0]['status'], 'accepted')
        self.assertEqual(self.store.review_job(self.job)['resolutions'], [])

    def test_actual_process_death_releases_lock_but_unexpired_lease_still_blocks_resolution(self):
        code = "from backend.service import Store; import os,sys; s=Store(sys.argv[1],bytes(range(32)),clock=lambda:1800000000); s.dispatch_one(lambda _: os._exit(23))"
        result = subprocess.run([sys.executable, '-c', code, str(self.path)], cwd=Path(__file__).parents[2],
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 23, result.stderr.decode(errors='replace'))
        self.assertEqual(self.jobs()[0]['status'], 'sending')
        with self.assertRaises(Conflict): self.store.reconcile_job(self.decision(), apply=True)
        self.clock[0] += 301
        self.store.reconcile_job(self.decision(), apply=True)
        self.assertEqual(self.jobs()[0]['status'], 'accepted')

    def test_other_process_cannot_acquire_active_delivery_lock(self):
        code = "from backend.dispatch_lock import delivery_lock,DeliveryBusy; import sys;\ntry:\n with delivery_lock(sys.argv[1]): pass\nexcept DeliveryBusy: sys.exit(17)"
        with delivery_lock(self.path):
            result = subprocess.run([sys.executable, '-c', code, str(self.path)], cwd=Path(__file__).parents[2],
                                    capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 17, result.stderr.decode(errors='replace'))
        with delivery_lock(self.path): pass

    def test_concurrent_conflicting_resolutions_never_both_apply(self):
        self.uncertain()
        def apply(outcome):
            try: return self.store.reconcile_job(self.decision(outcome=outcome), apply=True)['result']
            except (Conflict, DeliveryBusy): return 'refused'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(apply, ['accepted', 'not_accepted']))
        self.assertEqual(results.count('refused'), 1)
        self.assertEqual(len(self.store.review_job(self.job)['resolutions']), 1)

    def test_audit_write_failure_rolls_back_resolution_and_status(self):
        self.uncertain()
        original = self.store.seal
        def fail(identity, value):
            if identity.endswith(':receipt'): raise RuntimeError('injected encryption failure')
            return original(identity, value)
        with patch.object(self.store, 'seal', side_effect=fail), self.assertRaises(RuntimeError):
            self.store.reconcile_job(self.decision(), apply=True)
        self.assertEqual(self.jobs()[0]['status'], 'uncertain')
        self.assertEqual(self.store.review_job(self.job)['resolutions'], [])

    def test_recovery_uncertainty_can_be_settled_before_new_episode(self):
        self.store.dispatch_one(lambda _: 'initial accepted')
        self.store.close(self.owner, self.eid, 'recovered', 'Better')
        self.job = self.jobs()[1]['id']
        self.uncertain()
        with self.assertRaises(Conflict): self.store.activate(self.owner, 'two', self.plan, link_ttl=3600)
        self.store.reconcile_job(self.decision(), apply=True)
        self.assertIsNotNone(self.store.activate(self.owner, 'two', self.plan, link_ttl=3600))

    def test_cli_requires_explicit_apply_and_never_prints_evidence(self):
        self.uncertain()
        path = Path(self.tmp.name) / 'decision.json'
        path.write_text(json.dumps(self.decision()), encoding='utf-8')
        for apply in (False, True, True):
            output = io.StringIO()
            with patch.dict(os.environ, {'AUTOFEVER_STORE_KEY_HEX': self.key.hex()}), contextlib.redirect_stdout(output):
                result = main(['--database', str(self.path), '--decision', str(path)] + (['--apply'] if apply else []))
            self.assertEqual(result, 0)
            self.assertNotIn('private-test', output.getvalue())
            self.assertEqual(self.jobs()[0]['status'], 'accepted' if apply else 'uncertain')
        path.write_text('{"job_id":"one","job_id":"two"}', encoding='utf-8')
        with self.assertRaises(Invalid): load_decision(path)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(['--database', str(self.path), '--job', self.job, '--apply'])

    def test_cli_review_conflict_and_missing_database_are_nonmutating(self):
        self.uncertain()
        path = Path(self.tmp.name) / 'decision.json'
        path.write_text(json.dumps(self.decision()), encoding='utf-8')
        output, errors = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {'AUTOFEVER_STORE_KEY_HEX': self.key.hex()}), contextlib.redirect_stdout(output):
            self.assertEqual(main(['--database', str(self.path), '--job', self.job]), 0)
        self.assertEqual(json.loads(output.getvalue())['status'], 'uncertain')
        self.assertNotIn('alice@example.invalid', output.getvalue())
        with delivery_lock(self.path), patch.dict(os.environ, {'AUTOFEVER_STORE_KEY_HEX': self.key.hex()}), contextlib.redirect_stderr(errors):
            self.assertEqual(main(['--database', str(self.path), '--decision', str(path), '--apply']), 3)
        self.assertEqual(self.jobs()[0]['status'], 'uncertain')
        missing = Path(self.tmp.name) / 'missing.sqlite3'
        with contextlib.redirect_stderr(errors):
            self.assertEqual(main(['--database', str(missing), '--job', self.job]), 2)
        self.assertFalse(missing.exists())
        self.assertNotIn('private-test', errors.getvalue())

    def test_worker_lock_contention_does_not_consume_a_job(self):
        from backend.smtp import SMTPSender
        from backend.tests.test_smtp import configuration
        from backend.worker import run_worker
        sender = SMTPSender(configuration(), 'synthetic-only')
        with patch.object(self.store, 'dispatch_one', side_effect=DeliveryBusy):
            self.assertEqual(run_worker(self.store, sender), 0)
            stop = threading.Event()
            with patch.object(stop, 'wait', side_effect=lambda _: stop.set()) as wait:
                self.assertEqual(run_worker(self.store, sender, max_jobs=None, stop=stop), 0)
                wait.assert_called_once_with(5)
        self.assertEqual(self.jobs()[0]['attempts'], 0)


if __name__ == '__main__':
    unittest.main()
