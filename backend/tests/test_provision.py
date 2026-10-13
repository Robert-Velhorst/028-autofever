"""Disposable local operator setup and real HTTP/subprocess tests; no providers."""

import contextlib
import http.client
import io
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

from backend import backup, provision
from backend.hosted import read_secret
from backend.local import make_local_server
from backend.service import Denied, Invalid, RestoreHeld, Store, encoded
from backend.tests.test_owner import saved_contacts, saved_profile


class ProvisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path, self.credential, self.keyfile = [self.root / name for name in ('state.sqlite3', 'owner.afowner', 'store.afkey')]
        self.key = bytes(range(32))
        backup.write_private(self.keyfile, self.key.hex().encode())
        provision.initialize(self.path, self.key)
        self.store = provision.open_store(self.path, self.key)

    def count(self, table):
        with contextlib.closing(backup.readonly(self.path)) as db:
            return db.execute('SELECT count(*) FROM ' + table).fetchone()[0]

    def raw_credential(self):
        return json.loads(self.credential.read_text(encoding='utf-8'))

    def sql(self, query, params=()):
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            db.execute(query, params)
            db.commit()

    def test_keygen_is_random_private_no_overwrite_and_key_reader_compatible(self):
        other = self.root / 'new.afkey'
        provision.generate_key(other)
        value = read_secret(other)
        self.assertEqual(len(bytes.fromhex(value)), 32)
        self.assertNotEqual(value, self.key.hex())
        with self.assertRaises(Invalid): provision.generate_key(other)
        self.assertEqual(read_secret(other), value)
        if os.name == 'posix': self.assertEqual(other.stat().st_mode & 0o777, 0o600)

    def test_init_is_empty_and_refuses_existing_files_or_sidecars(self):
        self.assertEqual(self.count('owners'), 0)
        self.assertEqual(self.count('jobs'), 0)
        before = self.path.read_bytes()
        with self.assertRaises(Invalid): provision.initialize(self.path, self.key)
        self.assertEqual(self.path.read_bytes(), before)
        target = self.root / 'new.sqlite3'
        journal = self.root / 'new.sqlite3-journal'
        journal.write_bytes(b'keep')
        with self.assertRaises(Invalid): provision.initialize(target, self.key)
        self.assertEqual(journal.read_bytes(), b'keep')
        self.assertFalse(target.exists())

    def test_setup_never_initializes_missing_empty_or_foreign_existing_source(self):
        missing = self.root / 'missing.sqlite3'
        with self.assertRaises(FileNotFoundError): provision.open_store(missing, self.key)
        self.assertFalse(missing.exists())
        empty = self.root / 'empty.sqlite3'
        empty.touch()
        with self.assertRaises(Invalid): provision.open_store(empty, self.key)
        self.assertEqual(empty.stat().st_size, 0)
        foreign = self.root / 'foreign.sqlite3'
        with contextlib.closing(sqlite3.connect(foreign)) as db:
            db.execute('CREATE TABLE keep(value TEXT)')
            db.commit()
        before = foreign.read_bytes()
        with self.assertRaises(Invalid): provision.open_store(foreign, self.key)
        self.assertEqual(foreign.read_bytes(), before)

    def test_enrollment_replay_check_and_no_plaintext_secret_in_database(self):
        self.assertEqual(provision.provision_owner(self.store, self.credential), {'replayed': False})
        artifact = self.raw_credential()
        self.assertEqual(len(artifact['capability']), 43)
        self.assertTrue(provision.check_owner(self.store, self.credential))
        reopened = Store(self.path, self.key)
        self.assertEqual(provision.provision_owner(reopened, self.credential, resume=True), {'replayed': True})
        self.assertIsNone(reopened.latest_episode(artifact['capability']))
        self.assertEqual(self.count('owners'), 1)
        self.assertEqual(self.count('metadata'), 2)
        self.assertEqual(self.count('jobs'), 0)
        self.assertNotIn(artifact['capability'].encode(), self.path.read_bytes())
        self.assertEqual(list(self.root.glob('.autofever-provision-*')), [])
        if os.name == 'posix':
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.credential.stat().st_mode & 0o777, 0o600)

    def test_second_fresh_attempt_never_replaces_existing_credential(self):
        provision.provision_owner(self.store, self.credential)
        before = self.credential.read_bytes()
        with self.assertRaises(Invalid): provision.provision_owner(self.store, self.credential)
        self.assertEqual(self.credential.read_bytes(), before)
        self.assertEqual(self.count('owners'), 1)

    def test_publication_failure_leaves_no_registered_owner(self):
        with patch.object(provision, 'publish_new', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError): provision.provision_owner(self.store, self.credential)
        self.assertFalse(self.credential.exists())
        self.assertEqual(self.count('owners'), 0)
        self.assertEqual(self.count('metadata'), 1)
        self.assertEqual(list(self.root.glob('.autofever-provision-*')), [])

    def test_failure_after_file_publication_can_resume_without_losing_token(self):
        publish = provision.publish_private
        def fail_after_publish(path, data):
            publish(path, data)
            raise OSError('synthetic post-publication failure')
        with patch.object(provision, 'publish_private', side_effect=fail_after_publish), self.assertRaises(OSError):
            provision.provision_owner(self.store, self.credential)
        before = self.credential.read_bytes()
        self.assertEqual(self.count('owners'), 0)
        with self.assertRaises(Denied): provision.check_owner(self.store, self.credential)
        self.assertEqual(provision.provision_owner(self.store, self.credential, resume=True), {'replayed': False})
        self.assertEqual(self.credential.read_bytes(), before)
        self.assertEqual(self.count('owners'), 1)

    def test_real_process_death_between_file_and_commit_is_resumable(self):
        script = '''
import os, sys
from backend import provision
from backend.hosted import read_secret
store = provision.open_store(sys.argv[1], bytes.fromhex(read_secret(sys.argv[2])))
publish = provision.publish_private
def die(path, data):
    publish(path, data)
    os._exit(91)
provision.publish_private = die
provision.provision_owner(store, sys.argv[3])
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.path), str(self.keyfile), str(self.credential)],
                                capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 91, result.stderr)
        self.assertEqual(result.stdout + result.stderr, b'')
        self.assertEqual(self.count('owners'), 0)
        before = self.credential.read_bytes()
        reopened = provision.open_store(self.path, self.key)
        provision.provision_owner(reopened, self.credential, resume=True)
        self.assertEqual(self.credential.read_bytes(), before)
        self.assertTrue(provision.check_owner(reopened, self.credential))
        self.assertEqual(self.count('owners'), 1)

    def test_tampering_wrong_path_wrong_key_and_duplicate_fields_are_refused(self):
        provision.provision_owner(self.store, self.credential)
        original = self.credential.read_bytes()
        for field, value in (('capability', 'x' * 43), ('database', '/somewhere/else'),
                             ('command', '00000000-0000-4000-8000-000000000000'), ('version', True), ('mac', '0' * 64)):
            record = json.loads(original)
            record[field] = value
            self.credential.write_bytes(encoded(record))
            with self.assertRaises(Invalid): provision.check_owner(self.store, self.credential)
        self.credential.write_bytes(b'{"version":1,' + original.lstrip()[1:])
        with self.assertRaises(Invalid): provision.check_owner(self.store, self.credential)
        self.credential.write_bytes(original)
        with self.assertRaises(Exception): provision.open_store(self.path, b'x' * 32)
        otherpath = self.root / 'another.sqlite3'
        provision.initialize(otherpath, self.key)
        other = provision.open_store(otherpath, self.key)
        with self.assertRaises(Invalid): provision.provision_owner(other, self.credential, resume=True)
        self.assertEqual(self.count('owners'), 1)
        self.assertTrue(provision.check_owner(self.store, self.credential))

    def test_real_process_death_after_sql_insert_recovers_hot_journal(self):
        script = '''
import os, sys
from contextlib import contextmanager
from backend import provision
from backend.hosted import read_secret
store = provision.open_store(sys.argv[1], bytes.fromhex(read_secret(sys.argv[2])))
transaction = store.transaction
active = []
@contextmanager
def tracked_transaction():
    with transaction() as db:
        db.execute('PRAGMA cache_size=1')
        db.execute('PRAGMA cache_spill=1')
        active.append(db)
        yield db
store.transaction = tracked_transaction
seal = store.seal
def die(identity, value):
    if identity.startswith('provision:'):
        # Force uncommitted dirty pages onto disk under synthetic cache pressure,
        # rather than merely leaving a zero-header, non-hot journal behind.
        active[-1].executemany('INSERT INTO owners VALUES (?)', [(format(i, '064x'),) for i in range(512)])
        os._exit(92)
    return seal(identity, value)
store.seal = die
provision.provision_owner(store, sys.argv[3])
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.path), str(self.keyfile), str(self.credential)],
                                capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 92, result.stderr)
        self.assertEqual(result.stdout + result.stderr, b'')
        self.assertTrue(Path(str(self.path) + '-journal').exists())
        with self.assertRaises(sqlite3.OperationalError):
            with contextlib.closing(backup.readonly(self.path)) as db:
                backup.check_identity(db, self.store)
        before = self.credential.read_bytes()
        reopened = provision.open_store(self.path, self.key)
        self.assertEqual(self.count('owners'), 0)
        self.assertEqual(self.count('metadata'), 1)
        provision.provision_owner(reopened, self.credential, resume=True)
        self.assertEqual(self.credential.read_bytes(), before)
        self.assertTrue(provision.check_owner(reopened, self.credential))
        self.assertEqual(self.count('owners'), 1)

    def test_missing_oversized_unknown_fields_and_insecure_permissions_refused(self):
        with self.assertRaises(FileNotFoundError): provision.provision_owner(self.store, self.credential, resume=True)
        provision.provision_owner(self.store, self.credential)
        original = self.credential.read_bytes()
        self.credential.write_bytes(b' ' * (provision.MAX_CREDENTIAL_BYTES + 1))
        with self.assertRaises(Invalid): provision.check_owner(self.store, self.credential)
        record = json.loads(original)
        record['unexpected'] = 'field'
        self.credential.write_bytes(encoded(record))
        with self.assertRaises(Invalid): provision.check_owner(self.store, self.credential)
        self.credential.write_bytes(original)
        if os.name == 'posix':
            self.credential.chmod(0o644)
            try:
                with self.assertRaises(Invalid): provision.check_owner(self.store, self.credential)
            finally:
                self.credential.chmod(0o600)

    def test_replay_never_recreates_removed_owner(self):
        provision.provision_owner(self.store, self.credential)
        self.sql('DELETE FROM owners')  # Synthetic future revocation/state-loss scenario.
        with self.assertRaises(Denied): provision.provision_owner(self.store, self.credential, resume=True)
        with self.assertRaises(Denied): provision.check_owner(self.store, self.credential)
        self.assertEqual(self.count('owners'), 0)
        self.assertEqual(self.count('metadata'), 2)

    def test_concurrent_fresh_provisioning_has_one_winner_and_resume_is_idempotent(self):
        def create():
            try: return provision.provision_owner(self.store, self.credential)
            except Invalid: return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: create(), range(2)))
        self.assertEqual(results.count({'replayed': False}), 1)
        self.assertEqual(results.count(None), 1)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: provision.provision_owner(self.store, self.credential, resume=True), range(4)))
        self.assertEqual(results, [{'replayed': True}] * 4)
        self.assertEqual(self.count('owners'), 1)

    def test_backups_authenticate_enrollment_audit_and_restores_refuse_setup(self):
        provision.provision_owner(self.store, self.credential)
        archive, restored = self.root / 'copy.afbackup', self.root / 'review.sqlite3'
        backup.create_backup(self.path, archive, self.key)
        self.assertEqual(backup.verify_backup(archive, self.key, work_directory=self.root)['counts']['owners'], 1)
        backup.restore_copy(archive, restored, self.key)
        with self.assertRaises(RestoreHeld): provision.open_store(restored, self.key)
        self.store.path = restored
        with self.assertRaises(RestoreHeld): provision.provision_owner(self.store, self.root / 'new.afowner')
        self.assertFalse((self.root / 'new.afowner').exists())
        self.store.path = self.path
        self.sql("UPDATE metadata SET value=? WHERE name LIKE 'provision:%'", (b'corrupt',))
        with self.assertRaises(Exception): backup.create_backup(self.path, self.root / 'bad.afbackup', self.key)

    def test_cli_process_creates_and_checks_without_printing_secrets(self):
        prefix = [sys.executable, '-W', 'error::ResourceWarning', '-m', 'backend.provision']
        arguments = ['--database', str(self.path), '--key-file', str(self.keyfile), '--credential-file', str(self.credential)]
        outputs = []
        for action, extra in (('owner', []), ('check-owner', []), ('owner', ['--resume'])):
            result = subprocess.run(prefix + [action] + arguments + extra, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, '')
            outputs.append(result.stdout)
        result = subprocess.run(prefix + ['owner'] + arguments, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 2)
        outputs.append(result.stdout + result.stderr)
        for secret in (self.key.hex(), self.raw_credential()['capability'], str(self.root), 'Traceback'):
            self.assertNotIn(secret, ''.join(outputs))
        self.assertEqual(self.count('jobs'), 0)

    def test_cli_keygen_init_and_existing_file_failure(self):
        newkey, newdb = self.root / 'cli.afkey', self.root / 'cli.sqlite3'
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            self.assertEqual(provision.main(['keygen', '--output', str(newkey)]), 0)
            self.assertEqual(provision.main(['init', '--database', str(newdb), '--key-file', str(newkey)]), 0)
            self.assertEqual(provision.main(['init', '--database', str(newdb), '--key-file', str(newkey)]), 2)
        self.assertNotIn(read_secret(newkey), output.getvalue() + errors.getvalue())
        self.assertEqual(backup.validate_database(newdb, bytes.fromhex(read_secret(newkey)))['counts']['owners'], 0)

    def test_provisioned_credential_works_over_real_http_without_delivery(self):
        provision.provision_owner(self.store, self.credential)
        token = self.raw_credential()['capability']
        with make_local_server(self.store, 0, owner=True) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            origin = f'http://127.0.0.1:{server.server_port}'
            def request(path, method='GET', data=None, bearer=token):
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                try:
                    connection.request(method, path, body=json.dumps(data) if data is not None else None,
                                       headers={'Origin': origin, 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + bearer})
                    response = connection.getresponse()
                    return response.status, json.loads(response.read())
                finally:
                    connection.close()
            try:
                self.assertEqual(request('/api/v1/owner/episode'), (200, {'data': None}))
                self.assertEqual(request('/api/v1/owner/episode', bearer='x' * 43)[0], 404)
                response = request('/api/v1/owner/episodes', 'POST', dict(command='prepared-owner', profile=saved_profile(),
                                   contacts=saved_contacts(), link_ttl=3600))
                self.assertEqual(response[0], 200)
                self.assertEqual([x['status'] for x in response[1]['data']['notifications']], ['queued', 'queued'])
                self.assertEqual(request('/api/v1/owner/episode')[1]['data']['id'], response[1]['data']['id'])
            finally:
                server.shutdown()
                thread.join(5)
                self.assertFalse(thread.is_alive())
        self.assertEqual(self.count('owners'), 1)


if __name__ == '__main__':
    unittest.main()
