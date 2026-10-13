import copy
import json
import tempfile
import unittest
from pathlib import Path

from backend.dispatch_lock import delivery_lock
from backend.owner_web import OwnerApp
from backend.profile import compile_profile
from backend.service import Store, Conflict, Invalid
from backend.web import RecipientApp
from backend.tests import test_web


def saved_profile():
    return {
        'id': 'ill', 'name': 'Plots ziek', 'message': 'Ik neem vandaag rust.',
        'recovery': 'Ik ben weer opgeknapt. Bedankt!', 'duration': 'Morgen', 'checkin': 4,
        'recipients': ['alice', 'bob'], 'overrides': {'bob': 'Ik ben vandaag afwezig.'},
        'tasks': [{'id': 'food', 'title': 'Boodschappen', 'description': 'Brood en soep graag.',
                   'assignees': ['alice'], 'when': 'Vanavond', 'repeat': 'daily', 'backup': 'bob'}],
    }


def saved_contacts():
    return [{'id': cid, 'name': name, 'group': 'Vrienden', 'phone': '', 'email': cid+'@example.invalid', 'channels': ['Email']}
            for cid, name in [('alice', 'Maya'), ('bob', 'Jules')]]


class OwnerTests(unittest.TestCase):
    request = test_web.WebTests.request

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.key = bytes(range(32))
        self.path = Path(self.tmp.name) / 'state.sqlite3'
        self.store = Store(self.path, self.key)
        self.owner = self.token = self.store.create_owner()
        self.other = self.store.create_owner()
        self.app = OwnerApp(self.store, 'http://127.0.0.1:8080')

    def tearDown(self):
        self.tmp.cleanup()

    def activate(self, **changes):
        body = {'command': 'one-press', 'profile': saved_profile(), 'contacts': saved_contacts(), 'link_ttl': 3600}
        body.update(changes)
        return self.request('/api/v1/owner/episodes', 'POST', body)

    def test_lossless_profile_and_recipient_privacy(self):
        response = self.activate()
        self.assertEqual(response['status'], 200)
        episode = json.loads(response['body'])['data']
        self.assertEqual(episode['snapshot']['preparation'], {'profile': saved_profile(), 'contacts': saved_contacts()})
        self.assertEqual(len(episode['notifications']), 2)
        sent = []
        while self.store.dispatch_one(lambda item: sent.append(item) or 'synthetic-only'):
            pass
        token = sent[0]['action_token']
        recipient = self.store.recipient(token)
        self.assertEqual(recipient['tasks'][0]['description'], 'Brood en soep graag.')
        for private in ['preparation', 'backup', 'bob', 'example.invalid']:
            self.assertNotIn(private, str(recipient))
        self.assertNotIn(token, str(self.store.episode(self.owner, episode['id'])))
        self.assertEqual(self.request('/api/v1/owner/episode', token=token)['status'], 404)

    def test_retry_after_restart_does_not_duplicate_and_changed_key_conflicts(self):
        first = self.activate()
        self.store = Store(self.path, self.key)
        self.app = OwnerApp(self.store, 'http://127.0.0.1:8080')
        self.assertEqual(first, self.activate())
        profile = saved_profile()
        profile['message'] = 'Changed'
        self.assertEqual(self.activate(profile=profile)['status'], 409)
        self.assertEqual(len(self.store.latest_episode(self.owner)['notifications']), 2)

    def test_latest_episode_is_owner_scoped_and_helper_outcomes_visible(self):
        episode = json.loads(self.activate()['body'])['data']
        self.assertIsNone(json.loads(self.request('/api/v1/owner/episode', token=self.other)['body'])['data'])
        messages = []
        self.store.dispatch_one(lambda item: messages.append(item) or 'synthetic-only')
        token = messages[0]['action_token']
        self.store.acknowledge(token)
        self.store.respond(token, 'food', 'accept')
        self.store.respond(token, 'food', 'complete')
        result = self.store.latest_episode(self.owner)
        self.assertEqual(result['id'], episode['id'])
        self.assertTrue(result['recipients'][0]['acknowledged'])
        self.assertEqual(result['tasks'][0]['state'], 'completed')

    def test_checkin_is_private_due_only_and_repeatable_after_owner_confirmation(self):
        now = [1_800_000_000]
        self.store.clock = lambda: now[0]
        episode = json.loads(self.activate()['body'])['data']
        self.assertEqual(episode['checkin'], {'interval_hours': 4, 'last_confirmed_at': None,
                                               'next_due_at': now[0] + 4 * 3600, 'due': False})
        path = '/api/v1/owner/episode-checkins'
        body = {'episode_id': episode['id'], 'command': 'checkin-one'}
        self.assertEqual(self.request(path, 'POST', body, token=self.other)['status'], 404)
        self.assertEqual(self.request(path, 'POST', body)['status'], 409)
        notifications_before = episode['notifications']
        now[0] += 4 * 3600
        first = self.request(path, 'POST', body)
        self.assertEqual(first['status'], 200)
        checked_view = json.loads(first['body'])['data']
        checked = checked_view['checkin']
        self.assertEqual(checked_view['notifications'], notifications_before)
        self.assertEqual(checked, {'interval_hours': 4, 'last_confirmed_at': now[0],
                                  'next_due_at': now[0] + 4 * 3600, 'due': False})
        self.assertEqual(len(checked_view['notifications']), 2)
        # An uncertain HTTP outcome can replay the same command without extending the interval.
        now[0] += 60
        self.assertEqual(self.request(path, 'POST', body)['status'], 200)
        self.assertEqual(json.loads(self.request('/api/v1/owner/episode')['body'])['data']['checkin']['last_confirmed_at'], checked['last_confirmed_at'])
        self.store = Store(self.path, self.key, clock=lambda: now[0])
        self.app = OwnerApp(self.store, 'http://127.0.0.1:8080')
        now[0] = checked['next_due_at']
        due = json.loads(self.request('/api/v1/owner/episode')['body'])['data']['checkin']
        self.assertTrue(due['due'])
        self.assertEqual(due['next_due_at'], checked['next_due_at'])
        replay = self.request(path, 'POST', body)
        self.assertEqual(replay['status'], 200)
        self.assertTrue(json.loads(replay['body'])['data']['checkin']['due'])
        self.assertEqual(self.request(path, 'POST', {'episode_id': episode['id'], 'command': 'checkin-two'})['status'], 200)
        self.assertFalse(json.loads(self.request('/api/v1/owner/episode')['body'])['data']['checkin']['due'])

    def test_checkin_requires_active_prepared_episode_and_valid_command(self):
        episode = json.loads(self.activate()['body'])['data']
        path = '/api/v1/owner/episode-checkins'
        malformed = self.request(path, 'POST', {'episode_id': episode['id'], 'command': 'bad command'})
        self.assertEqual(malformed['status'], 400)
        close = {'episode_id': episode['id'], 'state': 'cancelled', 'recovery_message': None}
        self.assertEqual(self.request('/api/v1/owner/episode-closures', 'POST', close)['status'], 200)
        self.assertEqual(self.request(path, 'POST', {'episode_id': episode['id'], 'command': 'checkin-one'})['status'], 409)

    def test_server_export_is_complete_owner_scoped_and_omits_capabilities(self):
        now = [1_800_000_000]
        self.store.clock = lambda: now[0]
        first = json.loads(self.activate()['body'])['data']
        now[0] += 4 * 3600
        self.store.confirm_checkin(self.owner, first['id'], 'export-checkin')
        self.store.close(self.owner, first['id'], 'cancelled')
        second = json.loads(self.activate(command='episode-two')['body'])['data']
        exported = self.store.export_owner(self.owner)
        self.assertEqual(exported['format'], 'autofever-owner-export')
        self.assertEqual([item['id'] for item in exported['episodes']], [first['id'], second['id']])
        self.assertEqual([item['state'] for item in exported['episodes']], ['cancelled', 'active'])
        self.assertEqual(exported['episodes'][0]['checkin']['last_confirmed_at'], now[0])
        self.assertFalse(exported['episodes'][0]['checkin']['due'])
        self.assertEqual(self.store.export_owner(self.other)['episodes'], [])
        serialized = json.dumps(exported)
        for private in (self.owner, self.other, 'action_token', 'smtp-accepted', 'access-token'):
            self.assertNotIn(private, serialized)
        response = self.request('/api/v1/owner/export')
        self.assertEqual(response['status'], 200)
        self.assertEqual(response['headers']['Cache-Control'], 'no-store')
        self.assertEqual(len(json.loads(response['body'])['data']['episodes']), 2)
        self.assertEqual(self.request('/api/v1/owner/export', token=self.other)['status'], 200)
        self.assertEqual(self.request('/api/v1/owner/export', token='A' * 43)['status'], 404)

    def test_owner_server_data_deletion_removes_only_live_records_and_is_repeatable(self):
        now = [1_800_000_000]
        self.store.clock = lambda: now[0]
        first = json.loads(self.activate()['body'])['data']
        dispatched = []
        self.assertTrue(self.store.dispatch_one(lambda job: dispatched.append(job) or 'synthetic-only'))
        helper_token = dispatched[0]['action_token']
        now[0] += 4 * 3600
        self.store.confirm_checkin(self.owner, first['id'], 'delete-checkin')
        self.store.update(self.owner, first['id'], 'delete-update', 'Synthetic update', ['alice'])
        self.store.close(self.owner, first['id'], 'cancelled')
        json.loads(self.activate(command='second-before-delete')['body'])
        other_episode = self.store.activate_profile(self.other, 'other-owner', saved_profile(), saved_contacts(), link_ttl=3600)

        body = {'confirmation': 'DELETE_MY_SERVER_DATA'}
        response = self.request('/api/v1/owner/data-deletion', 'POST', body)
        self.assertEqual(response['status'], 200)
        self.assertEqual(json.loads(response['body'])['data'], {'deleted_episodes': 2})
        self.assertIsNone(self.store.latest_episode(self.owner))
        self.assertEqual(self.store.latest_episode(self.other)['id'], other_episode)
        self.assertEqual(self.store.export_owner(self.owner)['episodes'], [])
        self.assertEqual(self.request('/api/v1/recipient', token=helper_token)['status'], 404)
        self.assertEqual(self.request('/api/v1/owner/data-deletion', 'POST', body)['status'], 200)
        self.assertEqual(json.loads(self.request('/api/v1/owner/data-deletion', 'POST', body)['body'])['data'],
                         {'deleted_episodes': 0})
        with self.store.transaction() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM metadata WHERE name=?', ('checkin:' + first['id'],)).fetchone())
            self.assertFalse(db.execute("SELECT 1 FROM metadata WHERE name LIKE 'update:%' ").fetchone())
            self.assertEqual(db.execute('SELECT COUNT(*) FROM episodes WHERE owner=?', (self.owner,)).fetchone()[0], 0)

        # Deleting history retains the provisioned owner capability for future use.
        restarted = self.activate(command='after-delete')
        self.assertEqual(restarted['status'], 200)
        self.assertEqual(self.store.latest_episode(self.owner)['state'], 'active')

    def test_owner_server_data_deletion_fails_closed_for_unresolved_or_active_delivery(self):
        episode = json.loads(self.activate()['body'])['data']
        body = {'confirmation': 'DELETE_MY_SERVER_DATA'}
        job_id = episode['notifications'][0]['id']
        with self.store.transaction() as db:
            db.execute("UPDATE jobs SET status='sending',attempts=1,lease=0 WHERE id=?", (job_id,))
        with self.assertRaises(Conflict):
            self.store.delete_owner_data(self.owner)
        with self.store.transaction() as db:
            db.execute("UPDATE jobs SET status='uncertain' WHERE id=?", (job_id,))
        with self.assertRaises(Conflict):
            self.store.delete_owner_data(self.owner)
        with self.store.transaction() as db:
            db.execute("UPDATE jobs SET status='queued',attempts=0,lease=NULL WHERE id=?", (job_id,))
        with delivery_lock(self.path):
            with self.assertRaises(Conflict):
                self.store.delete_owner_data(self.owner)
        self.assertEqual(self.request('/api/v1/owner/data-deletion', 'POST',
                                      {'confirmation': 'DELETE_MY_SERVER_DATA', 'extra': True})['status'], 400)
        self.assertEqual(self.request('/api/v1/owner/data-deletion', 'GET')['status'], 405)
        self.assertEqual(self.request('/api/v1/owner/data-deletion', 'POST', body, token=self.other)['status'], 200)
        self.assertEqual(self.store.delete_owner_data(self.owner), 1)
        self.assertIsNone(self.store.latest_episode(self.owner))

    def test_recovery_targets_accepted_only_and_closure_is_repeatable(self):
        episode = json.loads(self.activate()['body'])['data']
        self.store.dispatch_one(lambda item: 'synthetic-only')
        closure = {'episode_id': episode['id'], 'state': 'recovered', 'recovery_message': saved_profile()['recovery']}
        wrong_owner = self.request('/api/v1/owner/episode-closures', 'POST', closure, token=self.other)
        self.assertEqual(wrong_owner['status'], 404)
        first = self.request('/api/v1/owner/episode-closures', 'POST', closure)
        self.assertEqual(first['status'], 200)
        self.assertEqual(first, self.request('/api/v1/owner/episode-closures', 'POST', closure))
        jobs = json.loads(first['body'])['data']['notifications']
        self.assertEqual([(j['recipient'], j['status']) for j in jobs if j['kind']=='recovery'], [('alice','queued')])

    def test_incomplete_multichannel_and_unknown_fields_do_not_start(self):
        for mutation in [lambda p,c: c[0].update(channels=['Email','SMS']),
                         lambda p,c: c[0].update(channels=['Push']),
                         lambda p,c: c[0].update(email=''),
                         lambda p,c: p.update(makeDefault=True),
                         lambda p,c: p['tasks'][0].update(backup='stranger'),
                         lambda p,c: p['tasks'][0].update(repeat='hourly'),
                         lambda p,c: p.update(checkin=True),
                         lambda p,c: c.append(copy.deepcopy(c[0]))]:
            profile, contacts = saved_profile(), saved_contacts()
            mutation(profile, contacts)
            self.assertEqual(self.activate(profile=profile, contacts=contacts)['status'], 400)
            self.assertIsNone(self.store.latest_episode(self.owner))

    def test_compiled_snapshot_cannot_diverge_from_saved_preferences(self):
        value = compile_profile(saved_profile(), saved_contacts())
        value['recipients'][0]['message'] = 'Changed behind the preview'
        with self.assertRaises(Invalid):
            self.store.activate(self.owner, 'tampered', value, link_ttl=3600)
        self.assertIsNone(self.store.latest_episode(self.owner))

    def test_owner_origin_method_limits_and_no_provisioning(self):
        self.assertEqual(self.request('/api/v1/owner/episodes', 'GET')['status'], 405)
        self.assertEqual(self.request('/api/v1/owner/episodes', 'POST', {}, HTTP_ORIGIN='https://evil.invalid')['status'], 403)
        self.assertEqual(self.request('/api/v1/owner/episodes', 'POST', {}, CONTENT_LENGTH=str(2*1024*1024+1))['status'], 413)
        self.assertEqual(self.request('/api/v1/owner/create', 'POST', {})['status'], 404)
        self.assertEqual(self.request('/api/v1/owner/episode-closures', 'POST', {'episode_id': [], 'state': 'cancelled', 'recovery_message': None})['status'], 400)

    def test_owner_page_has_hashed_scripts_and_no_key_in_document(self):
        page = self.request('/owner')
        self.assertEqual(page['status'], 200)
        csp = page['headers']['Content-Security-Policy']
        self.assertIn('sha256-', csp)
        self.assertNotIn("script-src 'unsafe-inline'", csp)
        self.assertNotIn(self.owner.encode(), page['body'])
        self.assertIn(b'/owner-bridge.js', page['body'])
        self.assertIn(b'/autofever-i18n.js', page['body'])
        bridge = self.request('/owner-bridge.js')
        self.assertEqual(bridge['status'], 200)
        self.assertIn(b'owner-retention-days', bridge['body'])
        self.assertIn(b'retention-setting', bridge['body'])
        locale = self.request('/autofever-i18n.js')
        self.assertEqual(locale['status'], 200)
        self.assertIn(b'language-toggle', locale['body'])
        self.app = RecipientApp(self.store, 'http://127.0.0.1:8080')
        for path in ['/owner', '/owner-bridge.js', '/autofever-i18n.js', '/api/v1/owner/episode']:
            self.assertEqual(self.request(path)['status'], 404)


if __name__ == '__main__':
    unittest.main()
