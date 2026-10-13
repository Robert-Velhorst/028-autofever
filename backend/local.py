"""Loopback-only development listener. Never use as a public server."""

import argparse
import os
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from backend.service import Store
from backend.web import RecipientApp


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        # Request URLs may contain accidentally pasted secrets. Do not log them.
        pass


class LocalServer(WSGIServer):
    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(10)
        return connection, address

    def handle_error(self, request, client_address):
        # A development transport error must not print request data/tracebacks.
        pass


def make_local_server(store, port=8080, *, owner=False):
    server = make_server('127.0.0.1', port, None, server_class=LocalServer, handler_class=QuietHandler)
    try:
        from backend.owner_web import OwnerApp
        app = OwnerApp if owner else RecipientApp
        server.set_app(app(store, f'http://127.0.0.1:{server.server_port}'))
    except BaseException:
        server.server_close()
        raise
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True, help='Existing dedicated Autofever service database')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--with-owner', action='store_true', help='Enable local owner UI/API (requires a privately provisioned owner capability)')
    args = parser.parse_args()
    if not args.database.is_file() or args.database.is_symlink():
        parser.error('An existing non-symlink Autofever database is required')
    try:
        key = bytes.fromhex(os.environ.pop('AUTOFEVER_STORE_KEY_HEX', ''))
        store = Store(args.database, key)
    except Exception:
        parser.error('Cannot open Autofever store. Check private key configuration and database locally.')
    with make_local_server(store, args.port, owner=args.with_owner) as server:
        print(f'Local recipient service: http://127.0.0.1:{server.server_port}/help', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
