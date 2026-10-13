"""Private operator setup: new key/store, resumable owner enrollment and local check.

No listener, episode activation, provider request, delivery or credential output.
"""

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import stat
import sys
import tempfile
import uuid
from contextlib import closing
from pathlib import Path

from backend.backup import check_identity, new_target, publish_new, regular_file, validate_database, write_private
from backend.hosted import read_secret
from backend.service import Conflict, Denied, Invalid, RecordCodec, Store, encoded, token_hash


MAX_CREDENTIAL_BYTES = 4096


def publish_private(path, data):
    target = new_target(path)
    with tempfile.TemporaryDirectory(prefix='.autofever-provision-', dir=target.parent) as tmp:
        stage = Path(tmp) / 'private-artifact'
        write_private(stage, data)
        publish_new(stage, target)


def generate_key(path):
    """A new 256-bit key; never replace or rotate an existing key implicitly."""
    publish_private(path, (secrets.token_hex(32) + '\n').encode('ascii'))


def initialize(database, key):
    """Publish a new, empty service store without replacing existing state."""
    target = new_target(database)
    with tempfile.TemporaryDirectory(prefix='.autofever-provision-', dir=target.parent) as tmp:
        stage = Path(tmp) / 'state.sqlite3'
        Store(stage, key)
        validate_database(stage, key)
        publish_new(stage, target)


def open_store(database, key):
    # Check a preexisting store before the constructor can initialize anything.
    path = regular_file(database)
    # mode=rw never creates a missing file, but allows SQLite to recover its own
    # hot rollback journal after a crash mid-enrollment. A read-only connection
    # cannot perform that recovery. No application records are changed here.
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=rw', uri=True, timeout=10)) as db:
        db.execute('PRAGMA trusted_schema=OFF')
        check_identity(db, RecordCodec(key))
    return Store(path, key)


def credential_mac(store, payload):
    return hmac.new(store.key, encoded(['autofever:owner-provision:v1', payload]), hashlib.sha256).hexdigest()


def unique_fields(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise Invalid('Duplicate credential field')
        result[name] = value
    return result


def read_credential(store, path):
    """Trusted local caller only. The returned object contains a bearer secret."""
    path = regular_file(path)
    if os.name == 'posix' and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise Invalid('Credential file must be private')
    with path.open('rb') as stream:
        data = stream.read(MAX_CREDENTIAL_BYTES + 1)
    if len(data) > MAX_CREDENTIAL_BYTES:
        raise Invalid('Oversized credential file')
    record = json.loads(data.decode('utf-8'), object_pairs_hook=unique_fields)
    if not isinstance(record, dict):
        raise Invalid('Invalid credential fields')
    expected = {'version', 'database', 'command', 'capability', 'mac'}
    if record.get('version') == 2:
        expected |= {'owner_hash', 'previous_hash'}
    if set(record) != expected:
        raise Invalid('Invalid credential fields')
    if type(record['version']) is not int or record['version'] not in (1, 2):
        raise Invalid('Unsupported credential version')
    if record['database'] != str(store.path.resolve()):
        raise Invalid('Credential belongs to a different database path')
    for name, pattern in (('command', r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}'),
                          ('capability', r'[A-Za-z0-9_-]{43}'), ('mac', r'[0-9a-f]{64}')):
        if not isinstance(record[name], str) or not re.fullmatch(pattern, record[name]):
            raise Invalid('Invalid credential value')
    payload = {name: value for name, value in record.items() if name != 'mac'}
    if not hmac.compare_digest(record['mac'], credential_mac(store, payload)):
        raise Invalid('Credential authentication failed')
    if record['version'] == 2 and any(not isinstance(record[k], str) or
            not re.fullmatch(r'[0-9a-f]{64}', record[k]) for k in ('owner_hash', 'previous_hash')):
        raise Invalid('Invalid credential binding')
    return record


def registration(store, db, record):
    if record['version'] != 1:
        raise Invalid('Replacement credential is not an enrollment')
    identity = 'provision:' + record['command']
    owner_hash = token_hash(record['capability'])
    digest = hashlib.sha256(encoded(record)).hexdigest()
    row = db.execute('SELECT value FROM metadata WHERE name=?', (identity,)).fetchone()
    if row is None:
        return identity, owner_hash, digest, False
    audit = store.open(identity, row['value'])
    if audit['owner_hash'] != owner_hash or audit['credential_digest'] != digest:
        raise Conflict('Enrollment command already has different content')
    if not db.execute('SELECT 1 FROM owners WHERE id=?', (owner_hash,)).fetchone():
        raise Denied('Owner no longer available; never re-enable through enrollment replay')
    store._owner(db, record['capability'])
    return identity, owner_hash, digest, True


def provision_owner(store, credential_file, *, resume=False):
    """Durably write the only raw credential BEFORE committing owner creation.

    An interrupted attempt is explicitly resumable from that private file. Exact
    replay checks its encrypted enrollment audit and never creates a second owner.
    """
    if type(resume) is not bool:
        raise Invalid('Explicit resume choice required')
    with store.transaction() as db:
        if resume:
            record = read_credential(store, credential_file)
        else:
            payload = {'version': 1, 'database': str(store.path.resolve()),
                       'command': str(uuid.uuid4()), 'capability': secrets.token_urlsafe(32)}
            record = {**payload, 'mac': credential_mac(store, payload)}
            data = encoded(record) + b'\n'
            if len(data) > MAX_CREDENTIAL_BYTES:
                raise Invalid('Credential path exceeds supported size')
            # On any publication/flush error the SQL transaction rolls back.
            # An output may nevertheless exist; retain it for explicit resume.
            publish_private(credential_file, data)
        identity, owner_hash, digest, replayed = registration(store, db, record)
        if not replayed:
            if db.execute('SELECT 1 FROM owners WHERE id=?', (owner_hash,)).fetchone():
                raise Conflict('Owner already exists without this enrollment audit')
            db.execute('INSERT INTO owners VALUES (?)', (owner_hash,))
            audit = {'version': 1, 'owner_hash': owner_hash, 'credential_digest': digest,
                     'created_at': int(store.clock())}
            db.execute('INSERT INTO metadata VALUES (?,?)', (identity, store.seal(identity, audit)))
    return {'replayed': replayed}


def check_owner(store, credential_file):
    record = read_credential(store, credential_file)
    with store.transaction() as db:
        if record['version'] == 1:
            if not registration(store, db, record)[3]:
                raise Denied('Enrollment has not committed; explicit resume required')
        else:
            from backend.owner_access import check_record
            check_record(store, db, record)
        store._owner(db, record['capability'])
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    keygen = actions.add_parser('keygen', help='Write a NEW private key file; never rotate an existing key')
    keygen.add_argument('--output', type=Path, required=True)
    for name in ('init', 'owner', 'check-owner'):
        command = actions.add_parser(name)
        command.add_argument('--database', type=Path, required=True)
        command.add_argument('--key-file', type=Path, required=True)
        if name != 'init':
            command.add_argument('--credential-file', type=Path, required=True)
        if name == 'owner':
            command.add_argument('--resume', action='store_true', help='Explicitly finish/recheck the SAME private enrollment file')
    args = parser.parse_args(argv)
    try:
        if args.action == 'keygen':
            generate_key(args.output)
            print('New private key file created. Protect it and arrange separate key recovery; no store or owner created.')
            return 0
        key = bytes.fromhex(read_secret(args.key_file))
        if args.action == 'init':
            initialize(args.database, key)
            print('New empty Autofever store created. No owner, listener, episode or delivery started.')
            return 0
        store = open_store(args.database, key)
        if args.action == 'owner':
            result = provision_owner(store, args.credential_file, resume=args.resume)
            print('Existing owner enrollment verified.' if result['replayed'] else 'Owner enrollment committed.')
            print('Credential is in the private file only. No episode activated and no message sent.')
        else:
            check_owner(store, args.credential_file)
            print('Local owner credential and enrollment verified. This does not verify browser access or hosted HTTPS.')
        return 0
    except Exception:
        print('Setup refused or interrupted. Check private paths, permissions, key, credential and store. '
              'Preserve existing files; if an owner file was created, inspect it privately and use explicit resume. '
              'No credential is printed.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
