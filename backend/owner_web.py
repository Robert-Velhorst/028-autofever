"""Opt-in local owner transport. No unauthenticated account provisioning."""
import base64
import hashlib
import json
import re
from pathlib import Path

from backend.web import RecipientApp, RequestError


OWNER_ROUTES = {
    '/api/v1/owner/episode': 'GET',
    '/api/v1/owner/export': 'GET',
    '/api/v1/owner/data-deletion': 'POST',
    '/api/v1/owner/episodes': 'POST',
    '/api/v1/owner/episode-closures': 'POST',
    '/api/v1/owner/episode-updates': 'POST',
    '/api/v1/owner/episode-checkins': 'POST',
    '/api/v1/owner/retention': 'GET',
    '/api/v1/owner/retention-setting': 'POST',
}


class OwnerApp(RecipientApp):
    def __init__(self, store, origin, *, https_proxy=False):
        super().__init__(store, origin, https_proxy=https_proxy)
        self.routes.update(OWNER_ROUTES)
        root = Path(__file__).parent
        html = (root.parent / 'illness-preview/index.html').read_text(encoding='utf-8')
        html = html.replace('<head>', '<head>\n<script src="/owner-bridge.js"></script>', 1)
        html = html.replace('<title>Autofever · Bewerkbare mobiele preview</title>', '<title>Autofever · Mijn melding</title>')
        self.assets['/owner'] = (html.encode(), 'text/html; charset=utf-8')
        self.assets['/owner-bridge.js'] = ((root / 'static/owner-bridge.js').read_bytes(), 'text/javascript; charset=utf-8')
        hashes = ['\'sha256-' + base64.b64encode(hashlib.sha256(script.encode()).digest()).decode() + '\''
                  for script in re.findall(r'<script>(.*?)</script>', html, re.S)]
        # Existing preview uses inline style attributes. Scripts require exact content hashes.
        self.owner_csp = ("default-src 'none'; script-src 'self' " + ' '.join(hashes) +
                          "; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; "
                          "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

    def policy(self, path):
        return self.owner_csp if path == '/owner' else super().policy(path)

    def body_limit(self, path):
        if path == '/api/v1/owner/episode-updates':
            return 32768
        return 2 * 1024 * 1024 if path == '/api/v1/owner/episodes' else super().body_limit(path)

    def api(self, path, method, token, value):
        if path not in OWNER_ROUTES:
            return super().api(path, method, token, value)
        if path.endswith('/episode'):
            result = self.store.latest_episode(token)
        elif path.endswith('/retention'):
            result = {'retention_days': self.store.retention_days(token)}
        elif path.endswith('/retention-setting'):
            if not isinstance(value, dict) or set(value) != {'retention_days'}:
                raise RequestError(400)
            result = {'retention_days': self.store.set_retention_days(token, value['retention_days'])}
        elif path.endswith('/export'):
            result = self.store.export_owner(token)
        elif path.endswith('/data-deletion'):
            if not isinstance(value, dict) or value != {'confirmation': 'DELETE_MY_SERVER_DATA'}:
                raise RequestError(400)
            result = {'deleted_episodes': self.store.delete_owner_data(token)}
        elif path.endswith('/episodes'):
            if not isinstance(value, dict) or set(value) != {'command', 'profile', 'contacts', 'link_ttl'}:
                raise RequestError(400)
            eid = self.store.activate_profile(token, value['command'], value['profile'], value['contacts'], link_ttl=value['link_ttl'])
            result = self.store.episode(token, eid)
        elif path.endswith('/episode-updates'):
            if (not isinstance(value, dict) or set(value) != {'episode_id', 'command', 'message', 'recipients'} or
                    not isinstance(value['episode_id'], str)):
                raise RequestError(400)
            self.store.update(token, value['episode_id'], value['command'], value['message'], value['recipients'])
            result = self.store.episode(token, value['episode_id'])
        elif path.endswith('/episode-checkins'):
            if (not isinstance(value, dict) or set(value) != {'episode_id', 'command'} or
                    not isinstance(value['episode_id'], str) or not isinstance(value['command'], str)):
                raise RequestError(400)
            self.store.confirm_checkin(token, value['episode_id'], value['command'])
            result = self.store.episode(token, value['episode_id'])
        else:
            if not isinstance(value, dict) or set(value) != {'episode_id', 'state', 'recovery_message'}:
                raise RequestError(400)
            if not isinstance(value['episode_id'], str):
                raise RequestError(400)
            if value['state'] == 'cancelled' and value['recovery_message'] is not None:
                raise RequestError(400)
            self.store.close(token, value['episode_id'], value['state'], value['recovery_message'])
            result = self.store.episode(token, value['episode_id'])
        return json.dumps({'data': result}, ensure_ascii=False).encode(), 'application/json; charset=utf-8'
