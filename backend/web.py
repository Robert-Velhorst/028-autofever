"""Local recipient HTTP boundary. Not an internet deployment configuration.

Only fixed assets and recipient-capability routes are exposed. No owner
provisioning, sender dispatch, database paths or debugging routes are public.
"""

import json
import re
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlsplit

from backend.service import Conflict, Denied, Invalid
from backend.origins import https_origin


ASSETS = {
    '/help': ('help.html', 'text/html; charset=utf-8'),
    '/help.css': ('help.css', 'text/css; charset=utf-8'),
    '/help.js': ('help.js', 'text/javascript; charset=utf-8'),
    '/favicon.svg': ('favicon.svg', 'image/svg+xml'),
}
ROUTES = {
    '/api/v1/recipient': 'GET',
    '/api/v1/recipient/acknowledgment': 'POST',
    '/api/v1/recipient/task-responses': 'POST',
}
ERRORS = {
    400: ('invalid_request', 'Ongeldig verzoek.'),
    403: ('forbidden', 'Verzoek niet toegestaan.'),
    404: ('unavailable', 'Deze link is niet beschikbaar.'),
    405: ('method_not_allowed', 'Methode niet toegestaan.'),
    409: ('conflict', 'De gegevens zijn intussen gewijzigd. Haal de actuele stand op.'),
    413: ('too_large', 'Verzoek te groot.'),
    415: ('unsupported_media_type', 'JSON vereist.'),
    429: ('rate_limited', 'Te veel verzoeken. Wacht even en probeer opnieuw.'),
    503: ('temporarily_unavailable', 'Tijdelijk niet beschikbaar. Probeer later opnieuw.'),
}


class RequestError(Exception):
    def __init__(self, status):
        self.status = status


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate field')
        result[key] = value
    return result


class RecipientApp:
    def __init__(self, store, origin, *, https_proxy=False):
        parsed = urlsplit(origin)
        if type(https_proxy) is not bool:
            raise ValueError('Explicit transport mode required')
        if https_proxy:
            https_origin(origin)
        elif (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or
                not parsed.port or origin != f'http://127.0.0.1:{parsed.port}'):
            raise ValueError('This local transport requires an exact IPv4 loopback origin with port')
        self.store, self.origin, self.host = store, origin, parsed.netloc
        self.https_proxy = https_proxy
        self.routes = dict(ROUTES)
        self.csp = ("default-src 'none'; script-src 'self'; style-src 'self'; "
                    "connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        root = Path(__file__).parent / 'static'
        self.assets = {route: ((root / name).read_bytes(), mime) for route, (name, mime) in ASSETS.items()}

    def __call__(self, env, start_response):
        extra = []
        try:
            body, mime = self.handle(env)
            status = 200
        except RequestError as exc:
            status = exc.status
        except Denied:
            status = 404
        except Conflict:
            status = 409
        except Invalid:
            status = 400
        except Exception:
            # Never serialize exceptions, tokens, paths or SQL details.
            status = 503
        if status != 200:
            code, message = ERRORS[status]
            body = json.dumps({'error': {'code': code, 'message': message}}, ensure_ascii=False).encode()
            mime = 'application/json; charset=utf-8'
            if status == 405:
                extra.append(('Allow', self.routes.get(env.get('PATH_INFO'), 'GET')))
            if status == 503:
                extra.append(('Retry-After', '5'))
            if status == 429:
                extra.append(('Retry-After', '60'))
        headers = [
            ('Content-Type', mime), ('Content-Length', str(len(body))),
            ('Cache-Control', 'no-store'), ('Referrer-Policy', 'no-referrer'),
            ('X-Content-Type-Options', 'nosniff'), ('X-Frame-Options', 'DENY'),
            ('Cross-Origin-Resource-Policy', 'same-origin'),
            ('Permissions-Policy', 'camera=(), microphone=(), geolocation=()'),
            ('Content-Security-Policy', self.policy(env.get('PATH_INFO'))),
        ]
        start_response(f'{status} {HTTPStatus(status).phrase}', headers + extra)
        return [body]

    def handle(self, env):
        if self.https_proxy and env.get('autofever.verified_proxy') is not True:
            raise RequestError(403)
        if env.get('HTTP_HOST') != self.host:
            raise RequestError(403)
        origin = env.get('HTTP_ORIGIN')
        if origin and origin != self.origin:
            raise RequestError(403)
        path, method = env.get('PATH_INFO'), env.get('REQUEST_METHOD')
        navigation = (path in ('/help', '/owner') and path in self.assets and method == 'GET' and
                      env.get('HTTP_SEC_FETCH_MODE') == 'navigate' and
                      env.get('HTTP_SEC_FETCH_DEST') == 'document')
        if env.get('HTTP_SEC_FETCH_SITE') == 'cross-site' and not navigation:
            raise RequestError(403)
        if env.get('QUERY_STRING'):
            raise RequestError(400)
        expected = 'GET' if path in self.assets else self.routes.get(path)
        if not expected:
            raise RequestError(404)
        if method != expected:
            raise RequestError(405)
        if path in self.assets:
            return self.assets[path]
        bearer = env.get('HTTP_AUTHORIZATION', '')
        if not re.fullmatch(r'Bearer [A-Za-z0-9_-]{43}', bearer):
            raise Denied()
        token = bearer[7:]
        value = None
        if method == 'POST':
            if origin != self.origin:
                raise RequestError(403)
            if env.get('CONTENT_TYPE', '').lower() not in ('application/json', 'application/json; charset=utf-8'):
                raise RequestError(415)
            length = env.get('CONTENT_LENGTH', '')
            if not re.fullmatch(r'[0-9]{1,10}', length) or env.get('HTTP_TRANSFER_ENCODING'):
                raise RequestError(400)
            length = int(length)
            if length > self.body_limit(path):
                raise RequestError(413)
            raw = env['wsgi.input'].read(length)
            if len(raw) != length:
                raise RequestError(400)
            try:
                value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object)
            except (ValueError, RecursionError):
                raise RequestError(400) from None
        return self.api(path, method, token, value)

    def policy(self, path):
        return self.csp

    def body_limit(self, path):
        return 8192

    def api(self, path, method, token, value):
        if method == 'POST':
            if path.endswith('/acknowledgment'):
                if value != {}:
                    raise RequestError(400)
                self.store.acknowledge(token)
            else:
                if (not isinstance(value, dict) or set(value) != {'task_id', 'action'} or
                        not isinstance(value['task_id'], str) or
                        not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value['task_id']) or
                        value['action'] not in ('accept', 'decline', 'complete', 'withdraw')):
                    raise RequestError(400)
                self.store.respond(token, value['task_id'], value['action'])
        body = json.dumps({'data': self.store.recipient(token)}, ensure_ascii=False).encode()
        return body, 'application/json; charset=utf-8'
