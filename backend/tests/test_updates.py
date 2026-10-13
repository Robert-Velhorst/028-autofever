import contextlib
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from backend import backup, migrate_updates, owner_access, provision
from backend.owner_web import OwnerApp
from backend.service import Store, RecordCodec, SCHEMA, Conflict, Denied, Invalid, SendFailure, RestoreHeld
from backend.tests.test_owner import saved_contacts, saved_profile
from backend.tests import test_web


class UpdateTests(unittest.TestCase):
    request = test_web.WebTests.request

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.key = bytes(range(32))
        self.clock = [1800000000]
        self.path = self.root / 'state.sqlite3'
        self.store = Store(self.path, self.key, clock=lambda:self.clock[0])
        self.owner = self.token = self.store.create_owner()
        self.other = self.store.create_owner()
        self.eid = self.store.activate_profile(self.owner, 'start', saved_profile(), saved_contacts(), link_ttl=3600)
        self.app = OwnerApp(self.store, 'http://127.0.0.1:8080')
        self.sent = []

    def send(self):
        return self.store.dispatch_one(lambda p:self.sent.append(p) or 'synthetic-only')

    def update(self, command='first', message='Nog een dag rust.', recipients=None):
        return self.store.update(self.owner, self.eid, command, message, ['alice'] if recipients is None else recipients)

    def view(self):
        return self.store.episode(self.owner, self.eid)

    def test_accepted_initial_required_and_selection_is_not_silently_expanded(self):
        with self.assertRaises(Conflict): self.update()
        self.send()
        with self.assertRaises(Conflict): self.update(recipients=['alice','bob'])
        selection = ['alice']
        original = self.store._episode
        def changed_caller_selection(*args):
            selection.append('bob')
            return original(*args)
        with patch.object(self.store,'_episode',side_effect=changed_caller_selection):
            self.update(recipients=selection)
        self.assertEqual(self.view()['updates'][0]['recipients'], ['alice'])
        self.assertEqual([j['recipient'] for j in self.view()['notifications'] if j['kind']=='update'], ['alice'])
        self.assertEqual(self.view()['snapshot']['preparation']['profile'], saved_profile())

    def test_replay_survives_restart_closure_and_rejects_changed_content(self):
        self.send(); self.send(); self.update(recipients=['bob','alice'])
        before = self.view()
        self.store = Store(self.path, self.key, clock=lambda:self.clock[0])
        self.update(recipients=['alice','bob'])
        self.assertEqual(self.view(), before)
        with self.assertRaises(Conflict): self.update(message='Different',recipients=['alice','bob'])
        self.store.close(self.owner,self.eid,'cancelled')
        self.update(recipients=['alice','bob'])
        self.assertEqual(len(self.view()['updates']),1)
        with self.assertRaises(Conflict): self.update(command='second')

    def test_recipient_sees_only_their_updates_without_acknowledging_them(self):
        self.send(); self.send(); self.update(message='<script>private update</script>')
        alice = self.store.recipient(self.sent[0]['action_token'])
        bob = self.store.recipient(self.sent[1]['action_token'])
        self.assertEqual(alice['updates'][0]['message'],'<script>private update</script>')
        self.assertEqual(bob['updates'],[])
        self.assertFalse(alice['acknowledged'])
        self.assertEqual(set(alice['updates'][0]),{'message','created_at'})
        with self.assertRaises(Denied): self.store.update(self.other,self.eid,'x','No',['alice'])
        with self.assertRaises(Denied): self.store.update(self.sent[0]['action_token'],self.eid,'x','No',['alice'])

    def test_queue_send_no_new_capability_and_cancellation_suppresses_queued_updates(self):
        self.send(); self.send(); self.update()
        self.send()
        self.assertEqual(self.sent[-1]['kind'],'update')
        self.assertNotIn('action_token',self.sent[-1])
        self.update(command='second')
        self.store.close(self.owner,self.eid,'recovered','Weer beter.')
        jobs = self.view()['notifications']
        self.assertEqual([j['status'] for j in jobs if j['kind']=='update'],['accepted','cancelled'])
        self.assertEqual(len([j for j in jobs if j['kind']=='recovery']),2)

    def test_pending_or_uncertain_update_blocks_later_updates_and_uncertainty_blocks_closure(self):
        self.send(); self.send(); self.update()
        with self.assertRaises(Conflict): self.update(command='second')
        def lost(_): raise SendFailure('uncertain')
        self.store.dispatch_one(lost)
        with self.assertRaises(Conflict): self.update(command='second')
        with self.assertRaises(Conflict): self.store.close(self.owner,self.eid,'recovered','Beter')
        self.assertEqual(self.view()['notifications'][-1]['status'],'uncertain')
        job = self.view()['notifications'][-1]['id']
        decision = dict(job_id=job,attempt=1,outcome='not_accepted',retry=True,
                        operator='synthetic-operator',evidence_source='provider_record',
                        evidence_reference='synthetic-test-only')
        self.assertEqual(self.store.reconcile_job(decision,apply=True)['result'],'queued')
        self.assertFalse(self.send())
        self.clock[0] += 30
        self.assertTrue(self.send())
        self.assertEqual(self.view()['notifications'][-1]['id'],job)
        self.assertEqual(self.view()['notifications'][-1]['status'],'accepted')
        self.update(command='second')

    def test_validation_and_update_limit(self):
        self.send(); self.send()
        for changes in ({'message':''},{'message':'x'*2001},{'recipients':[]},{'recipients':['alice','alice']},
                        {'recipients':['alice',{}]},{'command':'bad:command'},{'recipients':'alice'}):
            with self.subTest(changes=changes), self.assertRaises(Invalid): self.update(**changes)
        for n in range(50):
            self.update(command='u'+str(n)); self.send()
        with self.assertRaises(Conflict): self.update(command='limit')
        self.update(command='u0')

    def test_concurrent_identical_requests_create_one_batch(self):
        self.send(); self.send()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _:Store(self.path,self.key).update(self.owner,self.eid,'same','Hello',['alice']), range(2)))
        self.assertEqual(len(self.view()['updates']),1)
        self.assertEqual(len(self.view()['notifications']),3)

    def test_failed_insert_rolls_back_entire_batch(self):
        self.send(); self.send()
        original = self.store._job
        def fail(db,eid,recipient,*args,**kwargs):
            if recipient['id']=='bob': raise RuntimeError('synthetic')
            return original(db,eid,recipient,*args,**kwargs)
        with patch.object(self.store,'_job',side_effect=fail),self.assertRaises(RuntimeError):
            self.update(recipients=['alice','bob'])
        self.assertEqual(self.view()['updates'],[])
        self.assertEqual(len(self.view()['notifications']),2)

    def test_http_contract_and_no_external_send(self):
        self.send()
        body = {'episode_id':self.eid,'command':'http','message':'Nog rust nodig','recipients':['alice']}
        path = '/api/v1/owner/episode-updates'
        self.assertEqual(self.request(path,'POST',body)['status'],200)
        self.assertEqual(self.request(path,'POST',body)['status'],200)
        self.assertEqual(self.request(path,'POST',{**body,'unexpected':True})['status'],400)
        self.assertEqual(self.request(path,'POST',body,token=self.other)['status'],404)
        self.assertEqual(self.request(path,'POST',body,HTTP_ORIGIN='https://wrong.invalid')['status'],403)
        self.assertEqual(self.request(path)['status'],405)
        self.assertEqual(len(self.sent),1)
        self.assertEqual(self.view()['notifications'][-1]['status'],'queued')

    def test_backup_restore_validates_updates_and_holds_copy(self):
        self.send(); self.update()
        archive,restored = self.root/'backup.afbackup', self.root/'review.sqlite3'
        backup.create_backup(self.path,archive,self.key)
        backup.verify_backup(archive,self.key,work_directory=self.root)
        backup.restore_copy(archive,restored,self.key)
        with self.assertRaises(RestoreHeld): Store(restored,self.key)
        with self.store.transaction() as db:
            db.execute("DELETE FROM metadata WHERE name LIKE 'update:%'")
        with self.assertRaises(Invalid): backup.validate_database(self.path,self.key)

    def test_v3_access_rotation_does_not_lower_compatibility_floor(self):
        old,new = self.root/'old.afowner', self.root/'new.afowner'
        provision.provision_owner(self.store,old)
        owner_access.rotate(self.store,old,new)
        owner_access.revoke(self.store,new)
        with self.store.transaction() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],3)


class UpdateMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path,self.archive = self.root/'legacy.sqlite3',self.root/'pre.afbackup'
        self.key = bytes(range(32))
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            db.executescript(SCHEMA)
            db.execute('PRAGMA application_id=1095128625')
            db.execute('PRAGMA user_version=1')
            db.execute('INSERT INTO metadata VALUES (?,?)',('key-check',RecordCodec(self.key).seal('key-check',{'version':1})))
            db.commit()
        self.store = Store(self.path,self.key)
        self.owner = self.store.create_owner()
        self.eid = self.store.activate_profile(self.owner,'start',saved_profile(),saved_contacts(),link_ttl=3600)
        self.store.dispatch_one(lambda p:'synthetic')

    def test_explicit_migration_preserves_legacy_rows_and_supports_updates(self):
        before = self.store.episode(self.owner,self.eid)
        with self.assertRaises(Conflict): self.store.update(self.owner,self.eid,'x','Hello',['alice'])
        self.assertEqual(migrate_updates.migrate(self.path,self.key,self.archive),{'migrated':True})
        self.assertEqual(self.store.episode(self.owner,self.eid),before)
        self.assertEqual(backup.verify_backup(self.archive,self.key,work_directory=self.root)['counts']['jobs'],2)
        reopened = Store(self.path,self.key)
        reopened.update(self.owner,self.eid,'x','Hello',['alice'])
        self.assertEqual(backup.validate_database(self.path,self.key)['counts']['jobs'],3)
        self.assertEqual(migrate_updates.migrate(self.path,self.key,self.root/'again.afbackup'),{'migrated':False})

    def test_backup_failure_leaves_schema_and_state_unchanged(self):
        before = self.path.read_bytes()
        self.archive.write_bytes(b'preserve')
        with self.assertRaises(Invalid): migrate_updates.migrate(self.path,self.key,self.archive)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(self.archive.read_bytes(),b'preserve')

    def test_pending_sending_refuses_migration_preserving_backup(self):
        with self.store.transaction() as db:
            db.execute("UPDATE jobs SET status='sending',attempts=1,lease=0 WHERE status='queued'")
        with self.assertRaises(Conflict): migrate_updates.migrate(self.path,self.key,self.archive)
        self.assertTrue(self.archive.exists())
        with self.store.transaction() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],1)

    def test_schema_failure_after_rename_rolls_back_and_keeps_snapshot(self):
        before = self.store.episode(self.owner,self.eid)
        bad = migrate_updates.SCHEMA_V3.replace('receipt BLOB','receipt ???')
        with patch.object(migrate_updates,'SCHEMA_V3',bad), self.assertRaises(sqlite3.OperationalError):
            migrate_updates.migrate(self.path,self.key,self.archive)
        self.assertEqual(self.store.episode(self.owner,self.eid),before)
        self.assertTrue(self.archive.exists())
        backup.validate_database(self.path,self.key)
        with self.store.transaction() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],1)

    def test_v2_revocation_survives_migration_and_backup_validation(self):
        old,new = self.root/'old.afowner',self.root/'new.afowner'
        provision.provision_owner(self.store,old)
        owner_access.rotate(self.store,old,new)
        migrate_updates.migrate(self.path,self.key,self.archive)
        with self.assertRaises(Denied): provision.check_owner(self.store,old)
        self.assertTrue(provision.check_owner(self.store,new))
        backup.validate_database(self.path,self.key)


if __name__ == '__main__':
    unittest.main()
