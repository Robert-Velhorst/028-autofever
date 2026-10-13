import io
import json
import tempfile
import unittest
from pathlib import Path
from wsgiref.util import setup_testing_defaults

from backend.service import Store
from backend.web import RecipientApp
from backend.tests.test_service import plan


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = [1800000000]
        self.store = Store(Path(self.tmp.name) / 'state.sqlite3', bytes(range(32)), clock=lambda: self.clock[0])
        self.owner = self.store.create_owner()
        self.episode = self.store.activate(self.owner, 'first', plan(), link_ttl=3600)
        envelopes = []
        while self.store.dispatch_one(lambda item: envelopes.append(item) or 'synthetic-acceptance'):
            pass
        self.token, self.other = [x['action_token'] for x in envelopes]
        self.app = RecipientApp(self.store, 'http://127.0.0.1:8080')

    def tearDown(self):
        self.tmp.cleanup()

    def request(self, path, method='GET', body=None, token=None, **overrides):
        env = {}
        setup_testing_defaults(env)
        raw = json.dumps(body).encode() if body is not None else b''
        env.update(PATH_INFO=path, REQUEST_METHOD=method, HTTP_HOST='127.0.0.1:8080',
                   CONTENT_LENGTH=str(len(raw)), CONTENT_TYPE='application/json',
                   HTTP_ORIGIN='http://127.0.0.1:8080', HTTP_AUTHORIZATION='Bearer ' + (token or self.token))
        env['wsgi.input'] = io.BytesIO(raw)
        env.update(overrides)
        result = {}
        def start(status, headers):
            result.update(status=int(status.split()[0]), headers=dict(headers))
        result['body'] = b''.join(self.app(env, start))
        return result

    def test_page_has_no_personal_data_and_security_headers(self):
        response = self.request('/help')
        self.assertEqual(response['status'], 200)
        self.assertNotIn(self.token.encode(), response['body'])
        self.assertNotIn(b'migraine', response['body'])
        self.assertEqual(response['headers']['Cache-Control'], 'no-store')
        self.assertEqual(response['headers']['Referrer-Policy'], 'no-referrer')
        self.assertIn("frame-ancestors 'none'", response['headers']['Content-Security-Policy'])

    def test_get_never_acknowledges_and_post_does(self):
        view = self.request('/api/v1/recipient')
        self.assertFalse(json.loads(view['body'])['data']['acknowledged'])
        reply = self.request('/api/v1/recipient/acknowledgment', 'POST', {})
        self.assertEqual(reply['status'], 200)
        self.assertTrue(json.loads(reply['body'])['data']['acknowledged'])

    def test_task_flow_with_conflict_and_completion(self):
        path = '/api/v1/recipient/task-responses'
        accepted = self.request(path, 'POST', {'task_id': 'food', 'action': 'accept'})
        self.assertEqual(accepted['status'], 200)
        conflict = self.request(path, 'POST', {'task_id': 'food', 'action': 'accept'}, token=self.other)
        self.assertEqual(conflict['status'], 409)
        self.assertNotIn(self.token.encode(), conflict['body'])
        completed = self.request(path, 'POST', {'task_id': 'food', 'action': 'complete'})
        self.assertEqual(json.loads(completed['body'])['data']['tasks'][0]['status'], 'completed')

    def test_claimant_can_withdraw_and_retry_the_recipient_task_action(self):
        path = '/api/v1/recipient/task-responses'
        accepted = self.request(path, 'POST', {'task_id': 'food', 'action': 'accept'})
        self.assertEqual(accepted['status'], 200)
        withdrawn = self.request(path, 'POST', {'task_id': 'food', 'action': 'withdraw'})
        self.assertEqual(withdrawn['status'], 200)
        task = json.loads(withdrawn['body'])['data']['tasks'][0]
        self.assertEqual(task['status'], 'pending')
        self.assertTrue(task['declined_by_you'])

        replay = self.request(path, 'POST', {'task_id': 'food', 'action': 'withdraw'})
        self.assertEqual(replay['status'], 200)
        self.assertEqual(json.loads(replay['body'])['data']['tasks'][0]['status'], 'pending')
        self.assertNotIn(self.token.encode(), withdrawn['body'])

    def test_invalid_owner_expired_and_closed_capabilities_have_same_error(self):
        expected = self.request('/api/v1/recipient', token='x' * 43)
        owner = self.request('/api/v1/recipient', token=self.owner)
        self.clock[0] += 3600
        expired = self.request('/api/v1/recipient')
        self.clock[0] -= 3600
        self.store.close(self.owner, self.episode, 'cancelled')
        closed = self.request('/api/v1/recipient')
        self.assertEqual(expected['status'], 404)
        for result in [owner, expired, closed]:
            self.assertEqual(result, expected)

    def test_cross_origin_and_host_rebinding_are_rejected(self):
        for extra in [dict(HTTP_ORIGIN='https://evil.example'), dict(HTTP_HOST='evil.example'),
                      dict(HTTP_SEC_FETCH_SITE='cross-site'), dict(HTTP_ORIGIN='null')]:
            self.assertEqual(self.request('/api/v1/recipient/acknowledgment', 'POST', {}, **extra)['status'], 403)
        self.assertFalse(self.store.recipient(self.token)['acknowledged'])

    def test_missing_origin_and_non_json_mutation_rejected(self):
        self.assertEqual(self.request('/api/v1/recipient/acknowledgment', 'POST', {}, HTTP_ORIGIN='')['status'], 403)
        self.assertEqual(self.request('/api/v1/recipient/acknowledgment', 'POST', {}, CONTENT_TYPE='text/plain')['status'], 415)

    def test_unknown_and_malformed_payloads_do_not_mutate(self):
        path = '/api/v1/recipient/task-responses'
        for body in [[], None, {'task_id': 'food'}, {'task_id': 'food', 'action': 'accept', 'extra': 'x'},
                     {'task_id': [], 'action': 'accept'}, {'task_id': 'food', 'action': 'delete'}]:
            self.assertEqual(self.request(path, 'POST', body)['status'], 400)
        duplicate = b'{"task_id":"food","action":"decline","action":"accept"}'
        result = self.request(path, 'POST', {}, **{'wsgi.input': io.BytesIO(duplicate), 'CONTENT_LENGTH': str(len(duplicate))})
        self.assertEqual(result['status'], 400)
        self.assertEqual(self.store.recipient(self.token)['tasks'][0]['status'], 'pending')

    def test_limits_methods_query_tokens_and_paths_fail_closed(self):
        self.assertEqual(self.request('/api/v1/recipient/acknowledgment', 'POST', {}, CONTENT_LENGTH='9000')['status'], 413)
        self.assertEqual(self.request('/api/v1/recipient/acknowledgment', 'GET')['status'], 405)
        self.assertEqual(self.request('/api/v1/recipient', QUERY_STRING='token=' + self.token)['status'], 400)
        for path in ['/backend/service.py', '/../state.sqlite3', '/api/v1/owners']:
            self.assertEqual(self.request(path)['status'], 404)

    def test_database_errors_are_generic(self):
        def unavailable(_):
            raise RuntimeError('secret path and password')
        self.store.recipient = unavailable
        result = self.request('/api/v1/recipient')
        self.assertEqual(result['status'], 503)
        self.assertNotIn(b'secret', result['body'])

    def test_nonlocal_origin_refused(self):
        with self.assertRaises(ValueError):
            RecipientApp(self.store, 'http://0.0.0.0:8080')

    def test_external_link_navigation_opens_only_generic_page(self):
        response = self.request('/help', HTTP_ORIGIN='', HTTP_SEC_FETCH_SITE='cross-site',
                                HTTP_SEC_FETCH_MODE='navigate', HTTP_SEC_FETCH_DEST='document')
        self.assertEqual(response['status'], 200)
        self.assertEqual(self.request('/api/v1/recipient', HTTP_SEC_FETCH_SITE='cross-site')['status'], 403)

    def test_body_framing_and_all_assets(self):
        for length in ['-1', '', 'abc']:
            self.assertEqual(self.request('/api/v1/recipient/acknowledgment', 'POST', {}, CONTENT_LENGTH=length)['status'], 400)
        for raw in [b'{', b'\xff', b'{}x', b'{"extra":true}']:
            response = self.request('/api/v1/recipient/acknowledgment', 'POST', {},
                                    **{'wsgi.input': io.BytesIO(raw), 'CONTENT_LENGTH': str(len(raw))})
            self.assertEqual(response['status'], 400)
        short = self.request('/api/v1/recipient/acknowledgment', 'POST', {}, CONTENT_LENGTH='3')
        self.assertEqual(short['status'], 400)
        for path in ['/help.js', '/help.css', '/favicon.svg']:
            response = self.request(path)
            self.assertEqual(response['status'], 200)
            self.assertEqual(int(response['headers']['Content-Length']), len(response['body']))
        self.assertFalse(self.store.recipient(self.token)['acknowledged'])


if __name__ == '__main__':
    unittest.main()
