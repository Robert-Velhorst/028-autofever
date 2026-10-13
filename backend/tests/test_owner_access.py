"""Synthetic access lifecycle, interruption, HTTP and backup regressions."""

import contextlib
import http.client
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from backend import backup, owner_access, provision
from backend.local import make_local_server
from backend.service import Conflict, Denied, Invalid, RestoreHeld, Store, RecordCodec, SCHEMA, token_hash
from backend.tests.test_owner import saved_contacts, saved_profile


class OwnerAccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.key = bytes(range(32))
        self.path = self.root / 'state.sqlite3'
        self.keyfile = self.root / 'store.afkey'
        backup.write_private(self.keyfile, self.key.hex().encode())
        # Exercise access upgrades from the original v1 format even though new
        # stores now start at v3 for update-message support.
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            db.executescript(SCHEMA)
            db.execute('PRAGMA application_id=1095128625')
            db.execute('PRAGMA user_version=1')
            db.execute('INSERT INTO metadata VALUES (?,?)', ('key-check', RecordCodec(self.key).seal('key-check', {'version':1})))
            db.commit()
        self.store = Store(self.path, self.key)
        self.old, self.new = self.root / 'old.afowner', self.root / 'new.afowner'
        provision.provision_owner(self.store, self.old)
        self.token = self.read(self.old)['capability']
        self.episode = self.store.activate_profile(self.token, 'one-press', saved_profile(), saved_contacts(), link_ttl=3600)

    def read(self, path):
        return provision.read_credential(self.store, path)

    def rows(self):
        with contextlib.closing(backup.readonly(self.path)) as db:
            return {name: db.execute('SELECT * FROM ' + name).fetchall()
                    for name in ('owners', 'episodes', 'jobs', 'recipients', 'tasks', 'declines')}

    def version(self):
        with contextlib.closing(backup.readonly(self.path)) as db:
            return db.execute('PRAGMA user_version').fetchone()[0]

    def rotate(self, **kwargs):
        return owner_access.rotate(self.store, self.old, self.new, **kwargs)

    def test_rotation_preserves_all_business_rows_and_retry_identity(self):
        before = self.rows()
        self.assertEqual(self.rotate(), {'replayed': False})
        new = self.read(self.new)['capability']
        self.assertNotEqual(new, self.token)
        reopened = provision.open_store(self.path, self.key)
        self.assertEqual(self.version(), 2)
        self.assertEqual(self.rows(), before)
        self.assertEqual(reopened.latest_episode(new)['id'], self.episode)
        self.assertEqual(reopened.activate_profile(new, 'one-press', saved_profile(), saved_contacts(), link_ttl=3600), self.episode)
        self.assertTrue(provision.check_owner(reopened, self.new))
        for action in (lambda: reopened.latest_episode(self.token),
                       lambda: provision.check_owner(reopened, self.old),
                       lambda: provision.provision_owner(reopened, self.old, resume=True)):
            with self.assertRaises(Denied): action()
        self.assertEqual(self.rows(), before)
        self.assertNotIn(new.encode(), self.path.read_bytes())
        if os.name == 'posix': self.assertEqual(self.new.stat().st_mode & 0o777, 0o600)

    def test_replay_and_chained_rotation_never_resurrect_prior_codes(self):
        self.rotate()
        self.assertEqual(self.rotate(resume=True), {'replayed': True})
        third = self.root / 'third.afowner'
        owner_access.rotate(self.store, self.new, third)
        with self.assertRaises(Denied): self.rotate(resume=True)
        with self.assertRaises(Denied): provision.check_owner(self.store, self.new)
        self.assertTrue(provision.check_owner(self.store, third))
        self.assertEqual(owner_access.revoke(self.store, self.old), {'replayed': True})
        self.assertTrue(provision.check_owner(self.store, third))

    def test_revoke_is_idempotent_preserves_queue_and_cannot_resume_enrollment(self):
        before = self.rows()
        self.assertEqual(owner_access.revoke(self.store, self.old), {'replayed': False})
        self.assertEqual(owner_access.revoke(self.store, self.old), {'replayed': True})
        with self.assertRaises(Denied): self.rotate()
        with self.assertRaises(Denied): provision.provision_owner(self.store, self.old, resume=True)
        self.assertFalse(self.new.exists())
        self.assertEqual(self.rows(), before)
        self.assertEqual(self.version(), 2)

    def test_other_owner_cannot_resume_replacement_or_read_history(self):
        self.rotate()
        other = self.root / 'other.afowner'
        provision.provision_owner(self.store, other)
        with self.assertRaises(Invalid): owner_access.rotate(self.store, other, self.new, resume=True)
        with self.assertRaises(Denied): self.store.episode(self.read(other)['capability'], self.episode)
        self.assertTrue(provision.check_owner(self.store, self.new))

    def test_uncommitted_enrollment_cannot_be_rotated_or_revoked(self):
        other = self.root / 'pending.afowner'
        with patch.object(provision, 'registration', side_effect=RuntimeError('synthetic')):
            with self.assertRaises(RuntimeError): provision.provision_owner(self.store, other)
        with self.assertRaises(Denied): owner_access.rotate(self.store, other, self.new)
        with self.assertRaises(Denied): owner_access.revoke(self.store, other)

    def test_publication_error_retains_old_access_and_explicit_resume(self):
        publish = provision.publish_private
        def fail_after(path, data):
            publish(path, data)
            raise OSError('synthetic')
        with patch.object(provision, 'publish_private', side_effect=fail_after):
            with self.assertRaises(OSError): self.rotate()
        self.assertEqual(self.version(), 1)
        self.assertTrue(provision.check_owner(self.store, self.old))
        with self.assertRaises(Denied): provision.check_owner(self.store, self.new)
        pending = self.new.read_bytes()
        with self.assertRaises(Invalid): self.rotate()
        self.assertEqual(self.rotate(resume=True), {'replayed': False})
        self.assertEqual(self.new.read_bytes(), pending)

    def test_failure_between_revocation_and_replacement_rolls_back_everything(self):
        write = owner_access.write_access
        def fail_new(store, db, record, owner, enabled):
            if enabled: raise RuntimeError('synthetic')
            write(store, db, record, owner, enabled)
        with patch.object(owner_access, 'write_access', side_effect=fail_new):
            with self.assertRaises(RuntimeError): self.rotate()
        self.assertEqual(self.version(), 1)
        self.assertTrue(provision.check_owner(self.store, self.old))
        self.assertEqual(self.rotate(resume=True), {'replayed': False})

    def test_revocation_wins_over_pending_rotation(self):
        with patch.object(owner_access, 'write_access', side_effect=RuntimeError('synthetic')):
            with self.assertRaises(RuntimeError): self.rotate()
        owner_access.revoke(self.store, self.old)
        with self.assertRaises(Denied): self.rotate(resume=True)
        with self.assertRaises(Denied): provision.check_owner(self.store, self.new)

    def test_two_concurrent_rotations_only_publish_one_successor(self):
        targets = [self.new, self.root / 'other-new.afowner']
        def run(target):
            try:
                return owner_access.rotate(Store(self.path, self.key), self.old, target)
            except Denied:
                return 'denied'
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(run, targets))
        self.assertEqual(result.count({'replayed': False}), 1)
        self.assertEqual(result.count('denied'), 1)
        self.assertEqual(sum(p.exists() for p in targets), 1)

    def test_process_death_mid_rotation_preserves_old_access_and_resumes(self):
        script = '''
import os, sys
from backend import owner_access, provision
store = provision.open_store(sys.argv[1], bytes(range(32)))
write = owner_access.write_access
def interrupted(store, db, record, owner, enabled):
    write(store, db, record, owner, enabled)
    if not enabled: os._exit(73)
owner_access.write_access = interrupted
owner_access.rotate(store, sys.argv[2], sys.argv[3])
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.path), str(self.old), str(self.new)],
                                capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 73)
        self.assertEqual(result.stdout + result.stderr, b'')
        self.store = provision.open_store(self.path, self.key)
        self.assertTrue(provision.check_owner(self.store, self.old))
        self.assertEqual(self.version(), 1)
        self.rotate(resume=True)
        self.assertTrue(provision.check_owner(self.store, self.new))

    def test_backup_roundtrip_preserves_revocation_and_remains_held(self):
        self.rotate()
        archive, restored = self.root / 'backup.afbackup', self.root / 'restored.sqlite3'
        backup.create_backup(self.path, archive, self.key)
        self.assertFalse(backup.verify_backup(archive, self.key, work_directory=self.root)['restore_held'])
        self.assertTrue(backup.restore_copy(archive, restored, self.key)['restore_held'])
        with contextlib.closing(backup.readonly(restored)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)
            row = db.execute('SELECT value FROM metadata WHERE name=?', ('owner-access:' + token_hash(self.token),)).fetchone()
            self.assertFalse(self.store.open('owner-access:' + token_hash(self.token), row[0])['enabled'])
        with self.assertRaises(RestoreHeld): provision.open_store(restored, self.key)

    def test_damaged_access_record_fails_closed_and_backup_refuses(self):
        self.rotate()
        with self.store.transaction() as db:
            name = 'owner-access:' + token_hash(self.token)
            db.execute('UPDATE metadata SET value=? WHERE name=?', (self.store.seal(name, {'enabled': True}), name))
        with self.assertRaises(Invalid): self.store.latest_episode(self.token)
        with self.assertRaises(Invalid): backup.validate_database(self.path, self.key)

    def test_real_http_rejects_old_code_accepts_same_episode_with_new_code(self):
        server = make_local_server(self.store, port=0, owner=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def get(token):
                conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                try:
                    conn.request('GET', '/api/v1/owner/episode', headers={'Authorization': 'Bearer ' + token})
                    response = conn.getresponse()
                    return response.status, response.read()
                finally:
                    conn.close()
            self.assertEqual(get(self.token)[0], 200)
            self.rotate()
            self.assertEqual(get(self.token)[0], 404)
            status, body = get(self.read(self.new)['capability'])
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)['data']['id'], self.episode)
        finally:
            server.shutdown()
            thread.join(5)
            server.server_close()
        self.assertFalse(thread.is_alive())

    def test_cli_never_prints_credentials_and_check_owner_supports_replacement(self):
        args = ['--database', str(self.path), '--key-file', str(self.keyfile), '--credential-file', str(self.old)]
        result = subprocess.run([sys.executable, '-m', 'backend.owner_access', 'rotate', *args, '--output', str(self.new)],
                                capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        new = self.read(self.new)['capability']
        self.assertNotIn(new.encode(), result.stdout + result.stderr)
        self.assertNotIn(self.token.encode(), result.stdout + result.stderr)
        self.assertNotIn(self.key.hex().encode(), result.stdout + result.stderr)
        args[-1] = str(self.new)
        check = subprocess.run([sys.executable, '-m', 'backend.provision', 'check-owner', *args], capture_output=True, timeout=20)
        self.assertEqual(check.returncode, 0, check.stderr)
        revoke = subprocess.run([sys.executable, '-m', 'backend.owner_access', 'revoke', *args], capture_output=True, timeout=20)
        self.assertEqual(revoke.returncode, 0, revoke.stderr)
        with self.assertRaises(Denied): provision.check_owner(self.store, self.new)


if __name__ == '__main__':
    unittest.main()
