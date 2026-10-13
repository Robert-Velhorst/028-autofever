import copy
import json
import tempfile
import unittest
from pathlib import Path

from backend.owner_web import OwnerApp
from backend.profile import compile_profile
from backend.service import Store, Invalid
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
        self.assertEqual(self.request('/owner-bridge.js')['status'], 200)
        self.app = RecipientApp(self.store, 'http://127.0.0.1:8080')
        for path in ['/owner', '/owner-bridge.js', '/api/v1/owner/episode']:
            self.assertEqual(self.request(path)['status'], 404)


if __name__ == '__main__':
    unittest.main()
