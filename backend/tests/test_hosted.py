import contextlib
import http.client
import io
import json
import logging
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults

from backend.hosted import HostedApp, PrivateTransportLog, RequestLimits, main, make_hosted_server, read_secret
from backend.origins import https_origin
from backend.service import Store
from backend.web import RecipientApp, RequestError
from backend.tests.test_owner import saved_profile, saved_contacts


class HostedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'state.sqlite3'
        self.key, self.proxy_key = bytes(range(32)), 'a' * 64
        self.store = Store(self.path, self.key)
        self.owner = self.store.create_owner()
        self.origin = 'https://autofever.example.invalid'
        self.app = HostedApp(self.store, self.origin, self.proxy_key)

    def request(self, path='/owner', method='GET', body=None, **changes):
        env = {}
        setup_testing_defaults(env)
        raw = json.dumps(body).encode() if body is not None else b''
        env.update(PATH_INFO=path, REQUEST_METHOD=method, HTTP_HOST='autofever.example.invalid',
                   REMOTE_ADDR='127.0.0.1', HTTP_ORIGIN=self.origin, CONTENT_LENGTH=str(len(raw)),
                   CONTENT_TYPE='application/json', HTTP_AUTHORIZATION='Bearer ' + self.owner,
                   HTTP_X_AUTOFEVER_PROXY_KEY=self.proxy_key, HTTP_X_AUTOFEVER_PROTO='https',
                   HTTP_X_AUTOFEVER_CLIENT_IP='192.0.2.1')
        env['wsgi.input'] = io.BytesIO(raw)
        env.update(changes)
        result = {}
        def start(status, headers): result.update(status=int(status[:3]), headers=dict(headers))
        result['body'] = b''.join(self.app(env, start))
        return result

    def test_strict_https_origin_and_development_guard(self):
        self.assertEqual(https_origin(self.origin), 'autofever.example.invalid')
        for origin in ('http://autofever.example.invalid', self.origin+'/', self.origin+'?a=b',
                       'https://user:pass@host.invalid', 'https://127.0.0.1', 'https://-bad.invalid',
                       'https://UPPER.invalid', 'https://host.invalid:0', 'https://host.invalid:443', 'https://host.invalid:99999'):
            with self.subTest(origin=origin), self.assertRaises(ValueError): https_origin(origin)
        with self.assertRaises(ValueError): RecipientApp(self.store, self.origin)
        self.app = RecipientApp(self.store, self.origin, https_proxy=True)
        self.assertEqual(self.request('/help')['status'], 403)

    def test_requires_exact_peer_secret_protocol_client_ip_and_host(self):
        for changes in ({'REMOTE_ADDR':'192.0.2.2'}, {'HTTP_X_AUTOFEVER_PROXY_KEY':''},
                        {'HTTP_X_AUTOFEVER_PROXY_KEY':'b'*64}, {'HTTP_X_AUTOFEVER_PROXY_KEY':'☀'},
                        {'HTTP_X_AUTOFEVER_PROTO':'http'}, {'HTTP_X_AUTOFEVER_CLIENT_IP':''},
                        {'HTTP_X_AUTOFEVER_CLIENT_IP':'192.0.2.1, 127.0.0.1'},
                        {'HTTP_X_AUTOFEVER_CLIENT_IP':'fe80::1%eth0'}, {'HTTP_HOST':'hire.example.invalid'}):
            with self.subTest(changes=changes): self.assertEqual(self.request(**changes)['status'], 403)
        self.assertEqual(self.request(HTTP_X_AUTOFEVER_CLIENT_IP='2001:db8::1')['status'], 200)

    def test_forwarded_headers_do_not_override_origin_or_client_authority(self):
        self.assertEqual(self.request(HTTP_X_FORWARDED_HOST='evil.invalid', HTTP_FORWARDED='host=evil.invalid;proto=http',
                                      HTTP_X_FORWARDED_FOR='127.0.0.1')['status'], 200)
        self.assertEqual(self.request(HTTP_ORIGIN='https://evil.invalid')['status'], 403)
        self.assertEqual(self.request(HTTP_X_AUTOFEVER_PROTO='http', HTTP_X_FORWARDED_PROTO='https')['status'], 403)

    def test_external_navigation_opens_generic_owner_page_not_cross_site_api(self):
        fields = dict(HTTP_ORIGIN='', HTTP_SEC_FETCH_SITE='cross-site',
                      HTTP_SEC_FETCH_MODE='navigate', HTTP_SEC_FETCH_DEST='document')
        self.assertEqual(self.request('/owner', **fields)['status'], 200)
        self.assertEqual(self.request('/api/v1/owner/episode', **fields)['status'], 403)

    def test_rate_limits_reject_before_mutation_and_expire(self):
        clock = [100.0]
        self.app.limits = RequestLimits(clock=lambda: clock[0], token_limit=1)
        self.assertEqual(self.request()['status'], 200)
        response = self.request('/api/v1/owner/episodes', 'POST',
                                {'command':'one', 'profile':saved_profile(), 'contacts':saved_contacts(), 'link_ttl':3600})
        self.assertEqual(response['status'], 429)
        self.assertEqual(response['headers']['Retry-After'], '60')
        self.assertIsNone(self.store.latest_episode(self.owner))
        clock[0] += 60
        self.assertEqual(self.request()['status'], 200)

    def test_ip_and_global_limits_and_capacity_fail_closed(self):
        for limits, requests in [(RequestLimits(ip_limit=1), [('192.0.2.1',''), ('192.0.2.1','Bearer '+'b'*43)]),
                                 (RequestLimits(global_limit=1), [('192.0.2.1',''), ('192.0.2.2','')])]:
            limits.check(*requests[0])
            with self.assertRaises(RequestError) as error: limits.check(*requests[1])
            self.assertEqual(error.exception.status, 429)
        limits = RequestLimits(capacity=1)
        with self.assertRaises(RequestError) as error: limits.check('192.0.2.1','')
        self.assertEqual(error.exception.status, 503)
        self.assertEqual(limits.buckets, {})

    def test_concurrent_limit_and_no_plaintext_keys(self):
        limits = RequestLimits(ip_limit=5)
        def check(_):
            try: limits.check('192.0.2.1', 'Bearer '+self.owner); return True
            except RequestError: return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(check, range(20))), 5)
        self.assertNotIn('192.0.2.1', str(limits.buckets))
        self.assertNotIn(self.owner, str(limits.buckets))

    def test_health_proves_key_check_and_never_discloses_database_details(self):
        response = self.request('/_health')
        self.assertEqual(json.loads(response['body']), {'status':'ready'})
        self.assertEqual(response['headers']['Cache-Control'], 'no-store')
        with self.store.transaction() as db:
            db.execute("UPDATE metadata SET value=? WHERE name='key-check'", (b'broken',))
        response = self.request('/_health')
        self.assertEqual(response['status'], 503)
        self.assertNotIn(str(self.path).encode(), response['body'])
        self.assertEqual(self.request('/_health', QUERY_STRING='secret=bad')['status'], 403)

    def test_owner_recipient_and_operator_boundaries_remain(self):
        response = self.request('/api/v1/owner/episodes', 'POST',
                                {'command':'one', 'profile':saved_profile(), 'contacts':saved_contacts(), 'link_ttl':3600})
        self.assertEqual(response['status'], 200)
        sent = []
        self.store.dispatch_one(lambda item: sent.append(item) or 'synthetic')
        token = sent[0]['action_token']
        self.assertEqual(self.request('/api/v1/owner/episode', HTTP_AUTHORIZATION='Bearer '+token)['status'], 404)
        self.assertEqual(self.request('/api/v1/recipient', HTTP_AUTHORIZATION='Bearer '+self.owner)['status'], 404)
        for route in ('/api/v1/reconcile', '/api/v1/dispatch', '/.env'):
            self.assertEqual(self.request(route)['status'], 404)
        response = self.request('/api/v1/recipient', HTTP_AUTHORIZATION='Bearer '+token)
        self.assertEqual(response['status'], 200)
        self.assertNotIn(b'bob', response['body'])
        self.assertNotIn(self.proxy_key.encode(), response['body'])

    def test_private_files_and_check_cli_do_not_start_listener(self):
        key_file, proxy_file = Path(self.tmp.name)/'key', Path(self.tmp.name)/'proxy'
        for path, value in ((key_file, self.key.hex()), (proxy_file, self.proxy_key)):
            path.write_text(value, encoding='ascii')
            path.chmod(0o600)
        args = ['--database',str(self.path),'--key-file',str(key_file),'--proxy-key-file',str(proxy_file),
                '--origin',self.origin,'--check']
        with patch('backend.hosted.make_hosted_server') as server, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(args), 0)
            server.assert_not_called()
            self.assertNotIn(self.proxy_key, output.getvalue())
        proxy_file.write_text(self.key.hex(), encoding='ascii')
        with contextlib.redirect_stderr(io.StringIO()): self.assertEqual(main(args), 2)
        if os.name == 'posix':
            key_file.chmod(0o644)
            with self.assertRaises(ValueError): read_secret(key_file)

    def test_transport_log_filter_removes_paths_secrets_and_exception_text(self):
        record = logging.LogRecord('waitress', logging.ERROR, __file__, 1,
                                   'Failed /help?secret=%s', (self.proxy_key,),
                                   (RuntimeError, RuntimeError(self.owner), None))
        self.assertTrue(PrivateTransportLog().filter(record))
        rendered = logging.Formatter().format(record)
        for secret in (self.proxy_key, self.owner, '/help?', 'RuntimeError'):
            self.assertNotIn(secret, rendered)
        self.assertEqual(record.levelno, logging.ERROR)

    def test_real_waitress_transport_accepts_only_proxy_contract(self):
        server = make_hosted_server(self.app, 0)
        thread_errors = []
        def run():
            try:
                server.run()
            except BaseException as error:
                thread_errors.append(error)
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        def call(path, *, headers=None, method='GET', body=None, read_body=True):
            connection = http.client.HTTPConnection('127.0.0.1', int(server.effective_port), timeout=5)
            try:
                connection.request(method, path, body=body, headers=headers or {})
                response = connection.getresponse()
                return response.status, dict(response.getheaders()), response.read() if read_body else b''
            finally: connection.close()
        headers = {'Host':'autofever.example.invalid', 'X-Autofever-Proxy-Key':self.proxy_key,
                   'X-Autofever-Proto':'https', 'X-Autofever-Client-IP':'192.0.2.1', 'Connection':'close'}
        try:
            self.assertEqual(server.effective_host, '127.0.0.1')
            self.assertEqual(call('/owner')[0], 403)
            self.assertEqual(call('/owner', headers=headers)[0], 200)
            status, _, body = call('/_health', headers=headers)
            self.assertEqual((status,json.loads(body)), (200,{'status':'ready'}))
            write_headers = {**headers,'Origin':self.origin,'Content-Type':'application/json','Authorization':'Bearer '+self.owner}
            payload = json.dumps({'command':'socket', 'profile':saved_profile(), 'contacts':saved_contacts(), 'link_ttl':3600})
            self.assertEqual(call('/api/v1/owner/episodes', headers=write_headers, method='POST', body=payload)[0], 200)
            self.assertEqual(len(self.store.latest_episode(self.owner)['notifications']), 2)
            # An early size rejection may reset TCP with unread oversized input;
            # its error body is not an application API response. Assert the status.
            self.assertEqual(call('/owner', headers={**headers,'X-Large':'a'*17000}, read_body=False)[0], 431)
            # Reject an oversized declared body before transferring its content.
            self.assertEqual(call('/api/v1/owner/episodes', headers={**write_headers, 'Content-Length':str(2*1024*1024+1)},
                                  method='POST', body=b'')[0], 413)
        finally:
            server.task_dispatcher.shutdown()
            # Closing sockets concurrently with select() can raise WinError 10038.
            # Waitress's trigger runs this callback in its own event-loop thread.
            # Keep the real server.run() path and surface any thread failures.
            if worker.is_alive():
                server.trigger.pull_trigger(lambda: server.asyncore.close_all(server._map))
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            server.close()
            server.asyncore.close_all(server._map)
            self.assertEqual(thread_errors, [])


if __name__ == '__main__': unittest.main()
