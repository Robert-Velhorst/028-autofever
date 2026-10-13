import contextlib
import io
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults

from backend import backup
from backend.dispatch_lock import DeliveryBusy
from backend.hosted import HostedApp
from backend.owner_web import OwnerApp
from backend.service import Invalid, RecordCodec, RestoreHeld, SendFailure, Store
from backend.tests.test_owner import saved_contacts, saved_profile
from backend.tests.test_service import plan


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path, self.archive, self.restored = [self.root / name for name in ('live.sqlite3', 'copy.afbackup', 'review.sqlite3')]
        self.key = bytes(range(32))
        self.clock = 1800000000
        self.store = Store(self.path, self.key, clock=lambda: self.clock)
        self.owner = self.store.create_owner()
        self.episode = self.store.activate(self.owner, 'first', plan(), link_ttl=3600)

    def rows(self, path, table):
        with contextlib.closing(backup.readonly(path)) as db:
            return db.execute('SELECT * FROM ' + table).fetchall()

    def sql(self, query, params=()):
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            db.execute(query, params)
            db.commit()

    def create(self):
        return backup.create_backup(self.path, self.archive, self.key)

    def restore(self):
        return backup.restore_copy(self.archive, self.restored, self.key)

    def assert_no_staging(self):
        self.assertEqual(list(self.root.glob('.autofever-*')), [])

    def test_roundtrip_preserves_every_table_and_authenticates_all_records(self):
        sent = []
        self.store.dispatch_one(lambda item: sent.append(item) or 'synthetic-accepted')
        self.store.acknowledge(sent[0]['action_token'])
        self.store.respond(sent[0]['action_token'], 'food', 'accept')
        original = self.path.read_bytes()
        created = self.create()
        self.assertEqual(created['counts']['jobs'], 2)
        verified = backup.verify_backup(self.archive, self.key, work_directory=self.root)
        self.assertEqual(verified, created)
        restored = self.restore()
        self.assertTrue(restored['restore_held'])
        for table in ('owners', 'episodes', 'recipients', 'tasks', 'declines', 'jobs'):
            self.assertEqual(self.rows(self.path, table), self.rows(self.restored, table), table)
        self.assertEqual(self.path.read_bytes(), original)
        marker = dict(self.rows(self.restored, 'metadata'))['restore-hold']
        record = RecordCodec(self.key).open('restore-hold', marker)
        self.assertEqual(record['backup_created_at'], created['backup_created_at'])
        self.assertEqual(len(record['archive_sha256']), 64)
        self.assert_no_staging()

    def test_encrypted_owner_checkin_survives_backup_verification_and_restore(self):
        self.store.close(self.owner, self.episode, 'cancelled')
        episode = self.store.activate_profile(self.owner, 'saved-checkin', saved_profile(), saved_contacts(), link_ttl=3600)
        self.clock += 4 * 3600
        self.store.confirm_checkin(self.owner, episode, 'checkin-one')
        with contextlib.closing(backup.readonly(self.path)) as db:
            blob = db.execute('SELECT value FROM metadata WHERE name=?', ('checkin:' + episode,)).fetchone()[0]
        self.assertNotIn(b'checkin-one', blob)
        created = self.create()
        self.assertEqual(backup.verify_backup(self.archive, self.key, work_directory=self.root), created)
        self.restore()
        restored_blob = dict(self.rows(self.restored, 'metadata'))['checkin:' + episode]
        self.assertEqual(RecordCodec(self.key).open('checkin:' + episode, restored_blob),
                         {'version': 1, 'command': 'checkin-one', 'confirmed_at': self.clock})

    def test_archive_encryption_randomization_and_private_file_mode(self):
        self.create()
        other = self.root / 'second.afbackup'
        backup.create_backup(self.path, other, self.key)
        data = self.archive.read_bytes()
        self.assertNotEqual(data, other.read_bytes())
        for private in (self.key, self.key.hex().encode(), self.owner.encode(), self.episode.encode(),
                        b'alice@example.invalid', b'Private migraine note', b'SQLite format 3'):
            self.assertNotIn(private, data)
        self.restore()
        if os.name == 'posix':
            self.assertEqual(self.archive.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.restored.stat().st_mode & 0o777, 0o600)

    def test_wrong_key_tampered_truncated_and_wrong_magic_never_publish(self):
        self.create()
        with self.assertRaises(Exception):
            backup.restore_copy(self.archive, self.restored, b'x' * 32)
        original = self.archive.read_bytes()
        for data in (original[:-1], original[:10], b'X' + original[1:],
                     original[:-1] + bytes([original[-1] ^ 1]), original + b'extra'):
            self.archive.write_bytes(data)
            with self.assertRaises(Exception):
                self.restore()
            self.assertFalse(self.restored.exists())
            self.assert_no_staging()

    def test_never_overwrites_archive_database_or_sidecar(self):
        self.archive.write_bytes(b'keep archive')
        with self.assertRaises(Invalid): self.create()
        self.assertEqual(self.archive.read_bytes(), b'keep archive')
        self.archive.unlink()
        self.create()
        self.restored.write_bytes(b'keep database')
        with self.assertRaises(Invalid): self.restore()
        self.assertEqual(self.restored.read_bytes(), b'keep database')
        self.restored.unlink()
        for suffix in ('-wal', '-shm', '-journal', '.dispatch.lock'):
            sidecar = Path(str(self.restored) + suffix)
            sidecar.write_bytes(b'keep sidecar')
            with self.assertRaises(Invalid): self.restore()
            self.assertEqual(sidecar.read_bytes(), b'keep sidecar')
            sidecar.unlink()
        self.assertFalse(self.restored.exists())

    def test_missing_empty_and_foreign_sources_unchanged(self):
        missing = self.root / 'missing.sqlite3'
        with self.assertRaises(FileNotFoundError): backup.create_backup(missing, self.archive, self.key)
        self.assertFalse(missing.exists())
        foreign = self.root / 'other.sqlite3'
        with contextlib.closing(sqlite3.connect(foreign)) as db:
            db.execute('CREATE TABLE keep_me(value TEXT)')
            db.commit()
        original = foreign.read_bytes()
        with self.assertRaises(Invalid): backup.create_backup(foreign, self.archive, self.key)
        self.assertEqual(foreign.read_bytes(), original)
        self.assertFalse(Path(str(foreign) + '.dispatch.lock').exists())
        empty = self.root / 'empty.sqlite3'
        empty.touch()
        with self.assertRaises(Invalid): backup.create_backup(empty, self.archive, self.key)
        self.assertEqual(empty.stat().st_size, 0)
        self.assertFalse(Path(str(empty) + '.dispatch.lock').exists())
        self.assertFalse(self.archive.exists())
        self.assert_no_staging()

    def test_schema_drift_including_indexes_and_triggers_is_refused(self):
        for query, undo in (
            ('DROP INDEX due_jobs', 'CREATE INDEX due_jobs ON jobs(status,due)'),
            ('CREATE VIEW surprise AS SELECT * FROM jobs', 'DROP VIEW surprise'),
            ('CREATE TRIGGER surprise AFTER INSERT ON owners BEGIN DELETE FROM jobs; END', 'DROP TRIGGER surprise'),
        ):
            self.sql(query)
            with self.assertRaises(Invalid): self.create()
            self.assertFalse(self.archive.exists())
            self.sql(undo)
        self.create()

    def test_ciphertext_corruption_and_foreign_relationship_are_refused(self):
        original = self.rows(self.path, 'episodes')[0][4]
        self.sql('UPDATE episodes SET data=?', (b'damaged',))
        with self.assertRaises(Exception): self.create()
        self.sql('UPDATE episodes SET data=?', (original,))
        self.sql("UPDATE jobs SET episode='missing-episode'")
        with self.assertRaises(Invalid): self.create()
        self.assertFalse(self.archive.exists())
        self.assert_no_staging()

    def test_wrong_source_key_does_not_modify_original(self):
        before = self.path.read_bytes()
        with self.assertRaises(Exception): backup.create_backup(self.path, self.archive, b'x' * 32)
        self.assertEqual(before, self.path.read_bytes())
        self.assertFalse(self.archive.exists())

    def test_restored_copy_denies_startup_and_every_existing_store_transaction(self):
        self.create()
        self.restore()
        with self.assertRaises(RestoreHeld): Store(self.restored, self.key)
        # Simulate an already constructed process whose file now contains a hold.
        # All live SQL entry points must check it, not just constructor startup.
        self.store.path = self.restored
        called = []
        operations = (
            lambda: self.store.create_owner(),
            lambda: self.store.episode(self.owner, self.episode),
            lambda: self.store.latest_episode(self.owner),
            lambda: self.store.recipient('a' * 43),
            lambda: self.store.acknowledge('a' * 43),
            lambda: self.store.respond('a' * 43, 'food', 'accept'),
            lambda: self.store.activate(self.owner, 'second', plan(), link_ttl=3600),
            lambda: self.store.close(self.owner, self.episode, 'cancelled'),
            lambda: self.store.quarantine_expired(),
            lambda: self.store.dispatch_one(lambda item: called.append(item) or 'not permitted'),
        )
        before = self.restored.read_bytes()
        for operation in operations:
            with self.assertRaises(RestoreHeld): operation()
        self.assertEqual(called, [])
        self.assertEqual(self.restored.read_bytes(), before)
        self.assertTrue(backup.validate_database(self.restored, self.key)['restore_held'])

    def test_held_recipient_owner_and_hosted_readiness_return_generic_503(self):
        envelopes = []
        self.store.dispatch_one(lambda item: envelopes.append(item) or 'synthetic-accepted')
        self.create()
        self.restore()
        self.store.path = self.restored
        for hosted in (False, True):
            origin = 'https://autofever.example.invalid' if hosted else 'http://127.0.0.1:8080'
            app = HostedApp(self.store, origin, 'a' * 64) if hosted else OwnerApp(self.store, origin)
            routes = [('/api/v1/recipient', envelopes[0]['action_token']), ('/api/v1/owner/episode', self.owner)]
            if hosted: routes.append(('/_health', self.owner))
            for path, token in routes:
                env = {}
                setup_testing_defaults(env)
                env.update(PATH_INFO=path, HTTP_HOST=origin.split('://')[1], HTTP_ORIGIN=origin,
                           HTTP_AUTHORIZATION='Bearer ' + token, REMOTE_ADDR='127.0.0.1',
                           HTTP_X_AUTOFEVER_PROXY_KEY='a' * 64, HTTP_X_AUTOFEVER_PROTO='https',
                           HTTP_X_AUTOFEVER_CLIENT_IP='192.0.2.1')
                response = {}
                def start(status, headers): response.update(status=int(status[:3]))
                body = b''.join(app(env, start))
                self.assertEqual(response['status'], 503, path)
                for private in (token.encode(), b'migraine', b'restore-hold'):
                    self.assertNotIn(private, body)

    def test_sending_uncertain_and_reconciliation_records_remain_evidence_not_retries(self):
        def uncertain(_): raise SendFailure('uncertain')
        self.store.dispatch_one(uncertain)
        job = self.store.episode(self.owner, self.episode)['notifications'][0]
        decision = dict(job_id=job['id'], attempt=1, outcome='accepted', retry=False,
                        operator='test operator', evidence_source='provider_record', evidence_reference='synthetic evidence')
        self.store.reconcile_job(decision, apply=True)
        self.sql("UPDATE jobs SET status='sending',attempts=1,lease=0 WHERE status='queued'")
        self.create()
        self.restore()
        self.assertEqual(self.rows(self.path, 'jobs'), self.rows(self.restored, 'jobs'))
        before = dict(self.rows(self.path, 'metadata'))
        after = dict(self.rows(self.restored, 'metadata'))
        for name, blob in before.items(): self.assertEqual(blob, after[name])
        self.store.path = self.restored
        with self.assertRaises(RestoreHeld): self.store.reconcile_job(decision, apply=True)

    def test_stale_snapshot_never_resends_later_accepted_job(self):
        self.create()  # Queued at snapshot time.
        self.assertTrue(self.store.dispatch_one(lambda _: 'synthetic-accepted-after-backup'))
        self.restore()
        self.assertEqual(self.rows(self.restored, 'jobs')[0][5], 'queued')
        with self.assertRaises(RestoreHeld): Store(self.restored, self.key)
        self.assertEqual(self.store.episode(self.owner, self.episode)['notifications'][0]['status'], 'accepted')

    def test_active_sender_excludes_backup_without_interrupting_sender(self):
        entered, release = threading.Event(), threading.Event()
        errors = []
        def send(_):
            entered.set()
            if not release.wait(5): raise RuntimeError('test sender timeout')
            return 'synthetic-accepted'
        def run():
            try: self.store.dispatch_one(send)
            except Exception as error: errors.append(error)
        thread = threading.Thread(target=run)
        thread.start()
        try:
            self.assertTrue(entered.wait(5))
            with self.assertRaises(DeliveryBusy): self.create()
            self.assertFalse(self.archive.exists())
        finally:
            release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.create()

    def test_wal_snapshot_includes_committed_state_not_uncommitted_writer(self):
        with contextlib.closing(sqlite3.connect(self.path)) as writer:
            self.assertEqual(writer.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
            writer.execute("UPDATE tasks SET state='accepted',claimant='alice'")
            writer.commit()
            writer.execute("UPDATE tasks SET state='completed'")
            self.create()
            writer.rollback()
        self.restore()
        self.assertEqual(self.rows(self.restored, 'tasks')[0][2:], ('accepted', 'alice'))
        self.assertFalse(Path(str(self.restored) + '-wal').exists())

    def test_source_changes_after_snapshot_do_not_mix_into_archive(self):
        validate = backup.validate_database
        def after_snapshot(path, key):
            result = validate(path, key)
            self.store.create_owner()
            return result
        with patch.object(backup, 'validate_database', side_effect=after_snapshot): self.create()
        self.assertEqual(len(self.rows(self.path, 'owners')), 2)
        self.restore()
        self.assertEqual(len(self.rows(self.restored, 'owners')), 1)

    def test_bounds_and_publication_failure_leave_no_partial_target(self):
        with patch.object(backup, 'MAX_DATABASE_BYTES', 1), self.assertRaises(Invalid): self.create()
        with patch.object(backup.os, 'link', side_effect=OSError('synthetic disk error')), self.assertRaises(OSError): self.create()
        self.assertFalse(self.archive.exists())
        self.assert_no_staging()
        self.create()
        with patch.object(backup, 'MAX_DATABASE_BYTES', 1), self.assertRaises(Invalid): self.restore()
        with patch.object(backup.os, 'link', side_effect=OSError('synthetic disk error')), self.assertRaises(OSError): self.restore()
        self.assertFalse(self.restored.exists())
        self.assert_no_staging()

    def test_held_backup_stays_held_and_does_not_replace_original_provenance(self):
        self.create()
        self.restore()
        second = self.root / 'held.afbackup'
        third = self.root / 'second-review.sqlite3'
        backup.create_backup(self.restored, second, self.key)
        backup.restore_copy(second, third, self.key)
        self.assertEqual(dict(self.rows(third, 'metadata'))['restore-hold'],
                         dict(self.rows(self.restored, 'metadata'))['restore-hold'])
        with self.assertRaises(RestoreHeld): Store(third, self.key)

    def test_hardlinked_inputs_refused_and_atomic_publish_race_preserves_winner(self):
        link = self.root / 'linked.sqlite3'
        os.link(self.path, link)
        try:
            with self.assertRaises(Invalid): self.create()
        finally:
            link.unlink()
        real_link = os.link
        def concurrent_target(stage, target):
            Path(target).write_bytes(b'other operation won')
            real_link(stage, target)
        with patch.object(backup.os, 'link', side_effect=concurrent_target), self.assertRaises(FileExistsError): self.create()
        self.assertEqual(self.archive.read_bytes(), b'other operation won')
        self.assert_no_staging()

    def test_cli_real_process_roundtrip_and_secret_free_failure(self):
        keyfile = self.root / 'private-key'
        backup.write_private(keyfile, self.key.hex().encode())
        prefix = [sys.executable, '-W', 'error::ResourceWarning', '-m', 'backend.backup', '--key-file', str(keyfile)]
        for args, expected in (
            (['create', '--database', str(self.path), '--archive', str(self.archive)], 'Encrypted backup created'),
            (['verify', '--archive', str(self.archive), '--work-directory', str(self.root)], 'authentication verified'),
            (['restore-copy', '--archive', str(self.archive), '--database', str(self.restored)], 'Quarantined restore copy'),
        ):
            result = subprocess.run(prefix + args, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(expected, result.stdout)
            self.assertEqual(result.stderr, '')
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = backup.main(['--key-file', str(keyfile), 'restore-copy', '--archive', str(self.archive), '--database', str(self.restored)])
        self.assertEqual(code, 2)
        for secret in (self.key.hex(), self.owner, str(self.root), 'Traceback'):
            self.assertNotIn(secret, out.getvalue() + err.getvalue())
        self.assert_no_staging()

    def test_all_encrypted_columns_are_checked_not_only_key_check(self):
        self.store.dispatch_one(lambda _: 'synthetic-receipt')
        self.sql("INSERT INTO metadata VALUES (?,?)", ('resolution:synthetic-job:1',
                 self.store.seal('resolution:synthetic-job:1', dict(decision={}, attempt=1, outcome='accepted',
                                                                 retry=False, result='accepted', recorded_at=self.clock))))
        for table, column, where in (
            ('jobs', 'payload', "status='accepted'"),
            ('jobs', 'receipt', "status='accepted'"),
            ('metadata', 'value', "name='resolution:synthetic-job:1'"),
        ):
            with contextlib.closing(backup.readonly(self.path)) as db:
                original = db.execute(f'SELECT {column} FROM {table} WHERE {where}').fetchone()[0]
            self.sql(f'UPDATE {table} SET {column}=? WHERE {where}', (b'damaged',))
            with self.assertRaises(Exception): self.create()
            self.assertFalse(self.archive.exists())
            self.sql(f'UPDATE {table} SET {column}=? WHERE {where}', (original,))

    def test_corrupt_hold_still_blocks_existing_store_and_startup(self):
        self.sql("INSERT INTO metadata VALUES ('restore-hold',?)", (b'damaged',))
        with self.assertRaises(RestoreHeld): Store(self.path, self.key)
        with self.assertRaises(RestoreHeld): self.store.create_owner()
        with self.assertRaises(Exception): self.create()
        self.assertFalse(self.archive.exists())

    def test_time_limits_abort_before_publication_and_clean_staging(self):
        with patch.object(backup, 'OPERATION_SECONDS', 0), self.assertRaises(Exception): self.create()
        self.assertFalse(self.archive.exists())
        self.assert_no_staging()
        self.create()
        with patch.object(backup, 'OPERATION_SECONDS', 0), self.assertRaises(Exception): self.restore()
        self.assertFalse(self.restored.exists())
        self.assert_no_staging()

    def test_hold_is_committed_and_validated_before_restore_publication(self):
        self.create()
        publish = backup.publish_new
        def inspect_stage(stage, target):
            self.assertFalse(target.exists())
            self.assertTrue(backup.validate_database(stage, self.key)['restore_held'])
            with self.assertRaises(RestoreHeld): Store(stage, self.key)
            publish(stage, target)
        with patch.object(backup, 'publish_new', side_effect=inspect_stage): self.restore()

    def test_symlink_source_and_target_refused(self):
        link = self.root / 'linked.sqlite3'
        try:
            link.symlink_to(self.path)
        except OSError:
            self.skipTest('Creating symlinks requires host permission')
        with self.assertRaises(Invalid): backup.create_backup(link, self.archive, self.key)
        self.archive.symlink_to(self.root / 'missing')
        with self.assertRaises(Invalid): self.create()
        self.assertTrue(self.archive.is_symlink())


if __name__ == '__main__':
    unittest.main()
