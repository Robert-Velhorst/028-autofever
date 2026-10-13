"""Explicit HTTPS reverse-proxy boundary; never the development listener."""
import argparse
import hashlib
import hmac
import ipaddress
import logging
import os
import re
import secrets
import signal
import stat
import sys
import threading
import time
from pathlib import Path

from waitress.server import create_server

from backend.owner_web import OwnerApp
from backend.service import Store
from backend.web import RequestError


class PrivateTransportLog(logging.Filter):
    def filter(self, record):
        # Waitress exception paths can include request paths or exception text.
        # Keep severity/occurrence observable, but never log their raw contents.
        record.msg, record.args = 'Autofever HTTP transport event; inspect aggregate health locally.', ()
        record.exc_info = record.exc_text = record.stack_info = None
        return True


class RequestLimits:
    """Bounded single-process limits. Hashed keys; no persistent client-IP logs."""
    def __init__(self, *, clock=time.monotonic, global_limit=600, ip_limit=120, token_limit=60, capacity=4096):
        self.clock = clock
        self.limits = (global_limit, ip_limit, token_limit)
        self.capacity = capacity
        self.salt = secrets.token_bytes(32)
        self.buckets = {}
        self.lock = threading.Lock()

    def check(self, address, bearer):
        keys = [('global', self.limits[0]), ('ip:' + address, self.limits[1])]
        if re.fullmatch(r'Bearer [A-Za-z0-9_-]{43}', bearer):
            keys.append(('token:' + bearer, self.limits[2]))
        keys = [(hmac.new(self.salt, key.encode(), hashlib.sha256).digest(), limit) for key, limit in keys]
        now = self.clock()
        with self.lock:
            self.buckets = {key: value for key, value in self.buckets.items() if value[0] > now}
            if len(self.buckets) + sum(key not in self.buckets for key, _ in keys) > self.capacity:
                raise RequestError(503)
            if any(self.buckets.get(key, (0, 0))[1] >= limit for key, limit in keys):
                raise RequestError(429)
            for key, _ in keys:
                expiry, used = self.buckets.get(key, (now + 60, 0))
                self.buckets[key] = (expiry, used + 1)


class HostedApp(OwnerApp):
    def __init__(self, store, origin, proxy_key, *, limits=None):
        if not isinstance(proxy_key, str) or not re.fullmatch(r'[0-9a-f]{64}', proxy_key):
            raise ValueError('Separate 32-byte proxy key encoded as lowercase hex required')
        super().__init__(store, origin, https_proxy=True)
        self._proxy_key = proxy_key
        self.limits = limits if limits is not None else RequestLimits()

    def handle(self, env):
        supplied = env.pop('HTTP_X_AUTOFEVER_PROXY_KEY', '')
        if (env.get('REMOTE_ADDR') != '127.0.0.1' or not isinstance(supplied, str) or
                not supplied.isascii() or not hmac.compare_digest(supplied, self._proxy_key) or
                env.get('HTTP_X_AUTOFEVER_PROTO') != 'https' or env.get('HTTP_HOST') != self.host):
            raise RequestError(403)
        try:
            raw_address = env.get('HTTP_X_AUTOFEVER_CLIENT_IP', '')
            if '%' in raw_address:
                raise ValueError()
            address = str(ipaddress.ip_address(raw_address))
        except ValueError:
            raise RequestError(403) from None
        env['autofever.verified_proxy'] = True
        env['wsgi.url_scheme'] = 'https'
        self.limits.check(address, env.get('HTTP_AUTHORIZATION', ''))
        if env.get('PATH_INFO') == '/_health':
            if env.get('REQUEST_METHOD') != 'GET' or env.get('QUERY_STRING') or env.get('HTTP_ORIGIN') not in (None, '', self.origin):
                raise RequestError(403)
            with self.store.transaction() as db:
                row = db.execute("SELECT value FROM metadata WHERE name='key-check'").fetchone()
                if row is None or self.store.open('key-check', row[0]) != {'version': 1}:
                    raise RequestError(503)
            return b'{"status":"ready"}', 'application/json; charset=utf-8'
        return super().handle(env)


def read_secret(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 128:
        raise ValueError('Use a private bounded credential file')
    mode = path.stat().st_mode
    if os.name == 'posix' and stat.S_IMODE(mode) & 0o077:
        raise ValueError('Credential file must not be readable by group or others')
    value = path.read_text(encoding='ascii').strip()
    if not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError('Credential must contain exactly 64 lowercase hex characters')
    return value


def make_hosted_server(app, port=28028):
    if not isinstance(app, HostedApp) or type(port) is not int or not 0 <= port <= 65535:
        raise ValueError('Explicit hosted app and loopback port required')
    for name in ('waitress', 'waitress.queue'):
        logger = logging.getLogger(name)
        if not any(isinstance(item, PrivateTransportLog) for item in logger.filters):
            logger.addFilter(PrivateTransportLog())
    return create_server(app, host='127.0.0.1', port=port, ipv6=False, threads=4,
                         connection_limit=64, backlog=32, channel_timeout=15, cleanup_interval=5,
                         max_request_header_size=16384, max_request_body_size=2 * 1024 * 1024,
                         inbuf_overflow=2 * 1024 * 1024 + 1, outbuf_overflow=8 * 1024 * 1024,
                         outbuf_high_watermark=8 * 1024 * 1024, expose_tracebacks=False,
                         clear_untrusted_proxy_headers=True, log_untrusted_proxy_headers=False,
                         log_socket_errors=False, ident='Autofever', asyncore_loop_timeout=0.1)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--proxy-key-file', type=Path, required=True)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--port', type=int, default=28028)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', action='store_true', help='Validate locally, without binding a listener')
    action.add_argument('--serve', action='store_true', help='Start behind the configured local HTTPS proxy')
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error('Choose an unused unprivileged loopback port')
    try:
        if not args.database.is_file() or args.database.is_symlink():
            raise ValueError('Existing dedicated database required')
        key, proxy_key = read_secret(args.key_file), read_secret(args.proxy_key_file)
        if hmac.compare_digest(key, proxy_key):
            raise ValueError('Database and proxy keys must differ')
        app = HostedApp(Store(args.database, bytes.fromhex(key)), args.origin, proxy_key)
        if args.check:
            print('Local configuration valid. No listener started; public HTTPS, capacity and delivery are unverified.')
            return 0
        server = make_hosted_server(app, args.port)
    except Exception:
        print('Hosted configuration refused. Check private credentials, origin, dedicated store and loopback port.', file=sys.stderr)
        return 2
    previous = {}
    def stop(*_):
        raise KeyboardInterrupt()
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, stop)
        print('Autofever loopback web service started. A configured HTTPS proxy is required.', flush=True)
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        server.task_dispatcher.shutdown()
        server.asyncore.close_all(server._map)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
