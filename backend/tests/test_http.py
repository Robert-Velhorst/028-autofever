"""Actual loopback HTTP tests; synthetic data, no provider or external network."""

import contextlib
import http.client
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path

from backend.local import make_local_server
from backend.service import Store
from backend.tests.test_service import plan


class HttpTests(unittest.TestCase):
    def test_real_transport_and_restart_persistence(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()) as logs:
            path, key = Path(tmp) / 'state.sqlite3', bytes(range(32))
            store = Store(path, key)
            owner = store.create_owner()
            episode = store.activate(owner, 'http-test', plan(), link_ttl=3600)
            envelopes = []
            while store.dispatch_one(lambda item: envelopes.append(item) or 'synthetic-only'):
                pass
            token = envelopes[0]['action_token']
            with make_local_server(store, 0) as server:
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                origin = f'http://127.0.0.1:{server.server_port}'
                def call(path, method='GET', body=None, authorized=True):
                    connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                    try:
                        headers = {'Origin': origin, 'Content-Type': 'application/json'}
                        if authorized:
                            headers['Authorization'] = 'Bearer ' + token
                        connection.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
                        response = connection.getresponse()
                        return response.status, response.read()
                    finally:
                        connection.close()
                try:
                    self.assertEqual(call('/help')[0], 200)
                    self.assertEqual(call('/api/v1/recipient', authorized=False)[0], 404)
                    self.assertFalse(json.loads(call('/api/v1/recipient')[1])['data']['acknowledged'])
                    self.assertEqual(call('/api/v1/recipient/acknowledgment', 'POST', {})[0], 200)
                    self.assertEqual(call('/api/v1/recipient/task-responses', 'POST', {'task_id': 'food', 'action': 'accept'})[0], 200)
                    self.assertEqual(call('/api/v1/recipient?token=' + token)[0], 400)
                    restarted = Store(path, key)
                    self.assertTrue(restarted.recipient(token)['acknowledged'])
                    self.assertTrue(restarted.recipient(token)['tasks'][0]['claimed_by_you'])
                    restarted.close(owner, episode, 'cancelled')
                    self.assertEqual(call('/api/v1/recipient')[0], 404)
                finally:
                    server.shutdown()
                    worker.join(timeout=5)
                    self.assertFalse(worker.is_alive())
            self.assertNotIn(token, logs.getvalue())


if __name__ == '__main__':
    unittest.main()
