import json
import io
import os
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from backend.dispatch_lock import delivery_lock
from backend import backup
from backend.owner_web import OwnerApp
from backend.retention import main as retention_main
from backend.service import Conflict, Invalid, Store, token_hash
from backend.tests import test_web
from backend.tests.test_owner import saved_contacts, saved_profile


class RetentionTests(unittest.TestCase):
    request = test_web.WebTests.request

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'state.sqlite3'
        self.key = bytes(range(32))
        self.now = [int(time.time())]
        self.store = Store(self.path, self.key, clock=lambda: self.now[0])
        self.owner = self.store.create_owner()
        self.token = self.owner
        self.other = self.store.create_owner()
        self.app = OwnerApp(self.store, 'http://127.0.0.1:8080')

    def episode(self, owner, command, created, *, state='cancelled', checkin=False):
        self.now[0] = created
        eid = self.store.activate_profile(owner, command, saved_profile(), saved_contacts(), link_ttl=3600)
        if checkin:
            self.now[0] += 4 * 3600
            self.store.confirm_checkin(owner, eid, command + '-checkin')
        if state != 'active':
            self.store.close(owner, eid, state, 'Ik ben hersteld.' if state == 'recovered' else None)
        return eid

    def test_optional_policy_is_owner_scoped_validated_and_encrypted(self):
        self.assertIsNone(self.store.retention_days(self.owner))
        read = self.request('/api/v1/owner/retention')
        self.assertEqual(read['status'], 200)
        self.assertEqual(json.loads(read['body'])['data'], {'retention_days': None})
        self.assertEqual(self.request('/api/v1/owner/retention', token=self.other)['status'], 200)
        self.assertEqual(self.request('/api/v1/owner/retention', token='A' * 43)['status'], 404)
        self.assertEqual(self.request('/api/v1/owner/retention-setting', token=self.owner)['status'], 405)
        self.assertEqual(self.request('/api/v1/owner/retention', 'POST', {'retention_days': 30})['status'], 405)
        self.assertEqual(self.request('/api/v1/owner/retention-setting', 'POST', {'retention_days': 30},
                                      HTTP_ORIGIN='https://untrusted.invalid')['status'], 403)
        for invalid in (0, -1, 3651, True, '30'):
            self.assertEqual(self.request('/api/v1/owner/retention-setting', 'POST',
                                          {'retention_days': invalid})['status'], 400)
        saved = self.request('/api/v1/owner/retention-setting', 'POST', {'retention_days': 30})
        self.assertEqual(saved['status'], 200)
        self.assertEqual(json.loads(saved['body'])['data'], {'retention_days': 30})
        self.assertEqual(self.store.retention_days(self.owner), 30)
        self.assertIsNone(self.store.retention_days(self.other))
        with self.store.transaction() as db:
            row = db.execute('SELECT value FROM metadata WHERE name=?',
                             ('retention:' + token_hash(self.owner),)).fetchone()
            self.assertIsNotNone(row)
            self.assertNotIn(b'retention_days', row['value'])
        disabled = self.request('/api/v1/owner/retention-setting', 'POST', {'retention_days': None})
        self.assertEqual(disabled['status'], 200)
        self.assertIsNone(self.store.retention_days(self.owner))
        with self.store.transaction() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM metadata WHERE name=?',
                                         ('retention:' + token_hash(self.owner),)).fetchone())

    def test_purge_removes_only_expired_closed_resolved_history_in_bounded_batches(self):
        now = self.now[0]
        day = 86400
        old = self.episode(self.owner, 'old', now - 40 * day, checkin=True)
        old_two = self.episode(self.owner, 'old-two', now - 35 * day)
        recent = self.episode(self.owner, 'recent', now - 29 * day)
        other_old = self.episode(self.other, 'other-old', now - 100 * day)
        queued = self.episode(self.owner, 'queued', now - 100 * day)
        uncertain = self.episode(self.owner, 'uncertain', now - 100 * day)
        active = self.episode(self.owner, 'active', now - 100 * day, state='active')
        with self.store.transaction() as db:
            queued_job = db.execute('SELECT id FROM jobs WHERE episode=? LIMIT 1', (queued,)).fetchone()['id']
            uncertain_job = db.execute('SELECT id FROM jobs WHERE episode=? LIMIT 1', (uncertain,)).fetchone()['id']
            db.execute("UPDATE jobs SET status='queued' WHERE id=?", (queued_job,))
            db.execute("UPDATE jobs SET status='uncertain' WHERE id=?", (uncertain_job,))
        self.store.set_retention_days(self.owner, 30)
        self.now[0] = now
        self.assertEqual(self.store.purge_expired_history(limit=1), 1)
        self.assertIsNotNone(self.store.episode(self.owner, old_two))
        self.assertEqual(self.store.purge_expired_history(limit=10), 1)
        remaining = {row['id'] for row in self.store.export_owner(self.owner)['episodes']}
        self.assertEqual(remaining, {recent, active, queued, uncertain})
        self.assertEqual({row['id'] for row in self.store.export_owner(self.other)['episodes']}, {other_old})
        with self.store.transaction() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM metadata WHERE name=?', ('checkin:' + old,)).fetchone())
            self.assertIsNone(db.execute('SELECT 1 FROM metadata WHERE name=?', ('closure:' + old,)).fetchone())
            self.assertIsNotNone(db.execute('SELECT 1 FROM metadata WHERE name=?',
                                            ('retention:' + token_hash(self.owner),)).fetchone())
            self.assertIsNone(db.execute('SELECT 1 FROM episodes WHERE id IN (?,?)', (old, old_two)).fetchone())

    def test_purge_skips_when_dispatch_or_reconciliation_owns_shared_lock(self):
        old = self.episode(self.owner, 'old', self.now[0] - 40 * 86400)
        self.store.set_retention_days(self.owner, 30)
        with delivery_lock(self.path):
            with self.assertRaises(Conflict):
                self.store.purge_expired_history()
        self.assertIsNotNone(self.store.episode(self.owner, old))

    def test_retention_period_starts_at_closure_and_legacy_closures_are_preserved(self):
        now = self.now[0]
        long_active = self.episode(self.owner, 'long-active', now - 100 * 86400, state='active')
        self.now[0] = now - 20 * 86400
        self.store.close(self.owner, long_active, 'cancelled')
        legacy = self.episode(self.owner, 'legacy-closed', now - 80 * 86400)
        with self.store.transaction() as db:
            db.execute('DELETE FROM metadata WHERE name=?', ('closure:' + legacy,))
        self.store.set_retention_days(self.owner, 30)
        self.now[0] = now
        self.assertEqual(self.store.purge_expired_history(), 0)
        remaining = {row['id'] for row in self.store.export_owner(self.owner)['episodes']}
        self.assertEqual(remaining, {long_active, legacy})

    def test_purge_rejects_invalid_batch_size(self):
        for invalid in (0, -1, 1001, True):
            with self.assertRaises(Invalid):
                self.store.purge_expired_history(limit=invalid)

    def test_encrypted_backup_validator_accepts_owner_retention_policy(self):
        self.store.set_retention_days(self.owner, 120)
        self.episode(self.owner, 'closed-for-backup', self.now[0] - 86400)
        self.assertEqual(backup.validate_database(self.path, self.key)['counts']['owners'], 2)

    def test_cli_check_is_nondestructive_and_purge_runs_the_opt_in_policy(self):
        old = self.episode(self.owner, 'cli-old', self.now[0] - 40 * 86400)
        self.store.set_retention_days(self.owner, 30)
        self.now[0] += 40 * 86400
        key_path = Path(self.tmp.name) / 'store-key'
        key_path.write_text(self.key.hex(), encoding='ascii')
        if os.name == 'posix':
            key_path.chmod(0o600)
        out = io.StringIO()
        args = ['--database', str(self.path), '--key-file', str(key_path)]
        with redirect_stdout(out):
            self.assertEqual(retention_main(args + ['--check']), 0)
        self.assertIsNotNone(self.store.episode(self.owner, old))
        with redirect_stdout(out):
            self.assertEqual(retention_main(args + ['--purge']), 0)
        self.assertEqual(self.store.export_owner(self.owner)['episodes'], [])


if __name__ == '__main__':
    unittest.main()
