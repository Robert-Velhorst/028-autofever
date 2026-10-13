import copy
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backend.service import Store, Conflict, Denied, Invalid, SendFailure


def plan():
    return {
        'recipients': [
            {'id': 'alice', 'channel': 'email', 'destination': 'alice@example.invalid', 'message': 'Private migraine note'},
            {'id': 'bob', 'channel': 'email', 'destination': 'bob@example.invalid', 'message': 'Absent today'},
        ],
        'tasks': [{'id': 'food', 'title': 'Bring soup', 'timing': 'This evening', 'assignees': ['alice', 'bob']}],
    }


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'state.sqlite3'
        self.key = bytes(range(32))
        self.clock = [1_800_000_000]
        self.store = Store(self.path, self.key, clock=lambda: self.clock[0])
        self.owner = self.store.create_owner()

    def tearDown(self):
        self.tmp.cleanup()

    def activate(self):
        return self.store.activate(self.owner, 'activation-1', plan(), link_ttl=3600)

    def token(self, episode, recipient):
        # Trusted sender receives the private token in the envelope, never a public owner/list response.
        envelopes = []
        while self.store.dispatch_one(lambda item: envelopes.append(item) or 'provider-id'):
            pass
        return next(x['action_token'] for x in envelopes if x['recipient_id'] == recipient)

    def test_restart_idempotency_and_immutable_snapshot(self):
        source = plan()
        first = self.store.activate(self.owner, 'same', source, link_ttl=3600)
        source['recipients'][0]['message'] = 'changed later'
        restarted = Store(self.path, self.key, clock=lambda: self.clock[0])
        self.assertEqual(first, restarted.activate(self.owner, 'same', plan(), link_ttl=3600))
        self.assertEqual(len(restarted.episode(self.owner, first)['notifications']), 2)
        with self.assertRaises(Conflict):
            restarted.activate(self.owner, 'same', source, link_ttl=3600)
        with self.assertRaises(Conflict):
            restarted.activate(self.owner, 'different-key', source, link_ttl=3600)

    def test_other_owner_cannot_read_or_close(self):
        episode = self.activate()
        stranger = self.store.create_owner()
        for operation in [lambda: self.store.episode(stranger, episode), lambda: self.store.close(stranger, episode, 'cancelled')]:
            with self.assertRaises(Denied):
                operation()

    def test_capability_hides_other_recipients_and_is_read_only(self):
        episode = self.activate()
        token = self.token(episode, 'bob')
        view = self.store.recipient(token)
        self.assertEqual(view['message'], 'Absent today')
        self.assertNotIn('alice', str(view))
        self.assertNotIn('Private migraine', str(view))
        self.assertNotIn('destination', view)
        self.assertFalse(view['acknowledged'])
        self.assertFalse(self.store.recipient(token)['acknowledged'])
        self.store.acknowledge(token)
        self.store.acknowledge(token)
        self.assertTrue(self.store.recipient(token)['acknowledged'])
        self.assertEqual(self.store.episode(self.owner, episode)['notifications'][1]['status'], 'accepted')

    def test_tasks_are_claimed_exclusively_and_done_only_by_claimant(self):
        episode = self.activate()
        envelopes = []
        while self.store.dispatch_one(lambda item: envelopes.append(item) or 'p'):
            pass
        alice, bob = [x['action_token'] for x in envelopes]
        self.store.respond(alice, 'food', 'accept')
        self.store.respond(alice, 'food', 'accept')
        with self.assertRaises(Conflict):
            self.store.respond(bob, 'food', 'accept')
        with self.assertRaises(Denied):
            self.store.respond(bob, 'food', 'complete')
        self.store.respond(alice, 'food', 'complete')
        self.assertEqual(self.store.recipient(alice)['tasks'][0]['status'], 'completed')

    def test_unassigned_task_is_not_visible_or_mutable(self):
        source = plan()
        source['tasks'][0]['assignees'] = ['alice']
        episode = self.store.activate(self.owner, 'single', source, link_ttl=3600)
        token = self.token(episode, 'bob')
        self.assertEqual(self.store.recipient(token)['tasks'], [])
        with self.assertRaises(Denied):
            self.store.respond(token, 'food', 'accept')

    def test_expired_and_closed_links_fail_without_disclosure(self):
        episode = self.activate()
        token = self.token(episode, 'alice')
        with self.assertRaises(Denied):
            self.store.recipient('not-a-token')
        self.clock[0] += 3600
        with self.assertRaises(Denied):
            self.store.acknowledge(token)

    def test_recovery_targets_only_accepted_initial_notifications(self):
        episode = self.activate()
        envelopes = []
        self.store.dispatch_one(lambda item: envelopes.append(item) or 'p')
        token = envelopes[0]['action_token']
        self.store.close(self.owner, episode, 'recovered', 'Recovered, thank you')
        self.store.close(self.owner, episode, 'recovered', 'Recovered, thank you')
        jobs = self.store.episode(self.owner, episode)['notifications']
        self.assertEqual([j['status'] for j in jobs if j['kind'] == 'illness'], ['accepted', 'cancelled'])
        self.assertEqual(len([j for j in jobs if j['kind'] == 'recovery']), 1)
        self.assertTrue(self.store.dispatch_one(lambda item: envelopes.append(item) or 'r'))
        self.assertNotIn('action_token', envelopes[-1])
        self.assertEqual(envelopes[-1]['message'], 'Recovered, thank you')
        with self.assertRaises(Denied):
            self.store.recipient(token)

    def test_cancel_queues_no_recovery_and_cancels_waiting_jobs(self):
        episode = self.activate()
        self.store.close(self.owner, episode, 'cancelled')
        self.assertFalse(self.store.dispatch_one(lambda item: self.fail('must not send')))
        self.assertEqual({x['status'] for x in self.store.episode(self.owner, episode)['notifications']}, {'cancelled'})

    def test_missing_sender_does_not_consume_queue(self):
        episode = self.activate()
        with self.assertRaises(Invalid):
            self.store.dispatch_one(None)
        self.assertEqual(self.store.episode(self.owner, episode)['notifications'][0]['attempts'], 0)

    def test_ambiguous_send_is_quarantined_not_retried(self):
        episode = self.activate()
        def timeout(item):
            raise TimeoutError('may have sent; alice@example.invalid secret')
        self.store.dispatch_one(timeout)
        jobs = self.store.episode(self.owner, episode)['notifications']
        self.assertEqual(jobs[0]['status'], 'uncertain')
        self.assertNotIn('secret', str(jobs))
        with self.assertRaises(Conflict):
            self.store.close(self.owner, episode, 'recovered', 'Recovered')
        sent = []
        self.store.dispatch_one(lambda item: sent.append(item['recipient_id']) or 'ok')
        self.assertEqual(sent, ['bob'])
        self.assertFalse(self.store.dispatch_one(lambda item: self.fail('no automatic replay')))

    def test_definite_failure_retries_with_delay_and_limit(self):
        episode = self.store.activate(self.owner, 'retry', plan(), link_ttl=86400)
        def unavailable(item):
            raise SendFailure('retryable')
        for attempt in range(5):
            self.store.dispatch_one(unavailable)
            self.store.dispatch_one(unavailable)
            self.assertFalse(self.store.dispatch_one(unavailable))
            self.clock[0] += 3600
        self.assertEqual({x['status'] for x in self.store.episode(self.owner, episode)['notifications']}, {'failed'})
        self.assertEqual({x['attempts'] for x in self.store.episode(self.owner, episode)['notifications']}, {5})

    def test_restart_marks_expired_inflight_as_uncertain(self):
        episode = self.activate()
        def process_dies(item):
            raise SystemExit()
        with self.assertRaises(SystemExit):
            self.store.dispatch_one(process_dies)
        self.clock[0] += 301
        restarted = Store(self.path, self.key, clock=lambda: self.clock[0])
        restarted.quarantine_expired()
        self.assertEqual(restarted.episode(self.owner, episode)['notifications'][0]['status'], 'uncertain')

    def test_concurrent_activation_and_dispatch_are_unique(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            episodes = list(pool.map(lambda _: self.activate(), range(4)))
        self.assertEqual(len(set(episodes)), 1)
        sent = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: self.store.dispatch_one(lambda item: sent.append(item['id']) or 'p'), range(4)))
        self.assertEqual(len(sent), 2)
        self.assertEqual(len(set(sent)), 2)

    def test_encryption_key_and_ciphertext_fail_closed(self):
        self.activate()
        raw = self.path.read_bytes()
        for secret in [b'Private migraine note', b'alice@example.invalid', self.owner.encode(), b'Bring soup']:
            self.assertNotIn(secret, raw)
        with self.assertRaises(Exception):
            Store(self.path, b'Z' * 32)

    def test_invalid_snapshot_never_partially_queues(self):
        for change in ['duplicate', 'unknown-helper', 'empty', 'header', 'unknown-field']:
            source = copy.deepcopy(plan())
            if change == 'duplicate': source['recipients'].append(source['recipients'][0])
            if change == 'unknown-helper': source['tasks'][0]['assignees'] = ['stranger']
            if change == 'empty': source['recipients'] = []
            if change == 'header': source['recipients'][0]['destination'] = 'a@example.invalid\r\nBcc: other@example.invalid'
            if change == 'unknown-field': source['recipients'][0]['hidden_extra'] = 'secret'
            with self.assertRaises(Invalid):
                self.store.activate(self.owner, 'invalid', source, link_ttl=3600)
        self.activate()

    def test_foreign_database_is_not_modified(self):
        foreign = Path(self.tmp.name) / 'hire-ai.sqlite3'
        with sqlite3.connect(foreign) as db:
            db.execute('CREATE TABLE unrelated (value TEXT)')
            db.execute("INSERT INTO unrelated VALUES ('preserve me')")
        db.close()
        original = foreign.read_bytes()
        with self.assertRaises(Invalid):
            Store(foreign, self.key)
        self.assertEqual(original, foreign.read_bytes())

    def test_ciphertext_cannot_be_swapped_between_recipients(self):
        self.activate()
        with self.store.transaction() as db:
            jobs = db.execute('SELECT id,payload FROM jobs ORDER BY rowid').fetchall()
            db.execute('UPDATE jobs SET payload=? WHERE id=?', (jobs[0]['payload'], jobs[1]['id']))
        self.store.dispatch_one(lambda _: 'ok')
        with self.assertRaises(Exception):
            self.store.dispatch_one(lambda _: self.fail('tampered payload must never be sent'))

    def test_failed_activation_rolls_back_recipients_and_jobs(self):
        original = self.store._job
        def fail_job(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('injected storage failure')
        self.store._job = fail_job
        with self.assertRaises(RuntimeError):
            self.activate()
        with self.store.transaction() as db:
            for table in ('episodes', 'recipients', 'tasks', 'jobs'):
                self.assertEqual(db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0)
        self.store._job = original
        self.activate()

    def test_concurrent_helpers_have_exactly_one_winner(self):
        self.activate()
        envelopes = []
        while self.store.dispatch_one(lambda item: envelopes.append(item) or 'p'):
            pass
        def accept(item):
            try:
                self.store.respond(item['action_token'], 'food', 'accept')
                return True
            except Conflict:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(accept, envelopes)), [False, True])

    def test_decline_is_private_and_can_be_changed_to_accept(self):
        episode = self.activate()
        envelopes = []
        while self.store.dispatch_one(lambda item: envelopes.append(item) or 'p'):
            pass
        alice, bob = [x['action_token'] for x in envelopes]
        self.store.respond(alice, 'food', 'decline')
        self.assertTrue(self.store.recipient(alice)['tasks'][0]['declined_by_you'])
        self.assertFalse(self.store.recipient(bob)['tasks'][0]['declined_by_you'])
        self.store.respond(alice, 'food', 'accept')
        self.assertFalse(self.store.recipient(alice)['tasks'][0]['declined_by_you'])

    def test_queued_message_with_expired_link_is_not_dispatched(self):
        episode = self.activate()
        self.clock[0] += 3600
        self.assertFalse(self.store.dispatch_one(lambda _: self.fail('expired link sent')))
        self.assertEqual({x['status'] for x in self.store.episode(self.owner, episode)['notifications']}, {'failed'})

    def test_close_during_dispatch_is_rejected(self):
        episode = self.activate()
        def sender(item):
            with self.assertRaises(Conflict):
                self.store.close(self.owner, episode, 'cancelled')
            return 'accepted-by-provider'
        self.store.dispatch_one(sender)
        self.assertEqual(self.store.episode(self.owner, episode)['state'], 'active')

    def test_missing_key_check_does_not_reinitialize_existing_database(self):
        self.activate()
        with self.store.transaction() as db:
            db.execute("DELETE FROM metadata WHERE name='key-check'")
        with self.assertRaises(Invalid):
            Store(self.path, self.key)

    def test_recovery_in_progress_blocks_conflicting_new_episode(self):
        episode = self.activate()
        self.store.dispatch_one(lambda _: 'p')
        self.store.close(self.owner, episode, 'recovered', 'Recovered')
        with self.assertRaises(Conflict):
            self.store.activate(self.owner, 'new', plan(), link_ttl=3600)
        self.store.dispatch_one(lambda _: 'recovery-accepted')
        self.assertIsNotNone(self.store.activate(self.owner, 'new', plan(), link_ttl=3600))


if __name__ == '__main__':
    unittest.main()
