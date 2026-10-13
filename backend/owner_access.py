"""Private operator rotation/revocation of owner access; never sends messages.

Stop all pre-access-management application processes before first use. Version 2
is a forward-only compatibility floor: old code does not enforce revocation.
"""

import argparse
import hashlib
import secrets
import sys
import uuid
from pathlib import Path

from backend import provision
from backend.hosted import read_secret
from backend.service import Conflict, Denied, Invalid, encoded, token_hash, validate_access


def digest(record):
    return hashlib.sha256(encoded(record)).hexdigest()


def access_row(store, db, capability_hash):
    identity = 'owner-access:' + capability_hash
    row = db.execute('SELECT value FROM metadata WHERE name=?', (identity,)).fetchone()
    return validate_access(store.open(identity, row['value'])) if row else None


def check_record(store, db, record, *, allow_revoked=False):
    """Authenticate registered file identity without resurrecting revoked access."""
    hashed = token_hash(record['capability'])
    owner = hashed if record['version'] == 1 else record['owner_hash']
    row = access_row(store, db, hashed)
    if row is not None:
        if row['owner_hash'] != owner or row['credential_digest'] != digest(record):
            raise Conflict('Credential does not match access record')
        if not row['enabled'] and not allow_revoked:
            raise Denied('Unavailable')
    elif record['version'] == 1:
        if not provision.registration(store, db, record)[3]:
            raise Denied('Enrollment not committed')
    else:
        raise Denied('Replacement not committed')
    if not db.execute('SELECT 1 FROM owners WHERE id=?', (owner,)).fetchone():
        raise Denied('Unavailable')
    return owner, row


def write_access(store, db, record, owner, enabled):
    identity = 'owner-access:' + token_hash(record['capability'])
    prior = access_row(store, db, token_hash(record['capability']))
    value = {'version': 1, 'owner_hash': owner, 'enabled': enabled,
             'credential_digest': digest(record),
             'created_at': prior['created_at'] if prior else int(store.clock())}
    validate_access(value)
    db.execute('INSERT INTO metadata VALUES (?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value',
               (identity, store.seal(identity, value)))


def rotate(store, credential_file, output, *, resume=False):
    if type(resume) is not bool:
        raise Invalid('Explicit resume required')
    with store.transaction() as db:
        old = provision.read_credential(store, credential_file)
        old_hash = token_hash(old['capability'])
        if resume:
            new = provision.read_credential(store, output)
            if new['version'] != 2 or new['previous_hash'] != old_hash:
                raise Invalid('Replacement does not match the previous credential')
            existing = access_row(store, db, token_hash(new['capability']))
            if existing is not None:
                owner, _ = check_record(store, db, new)
                previous_owner, previous = check_record(store, db, old, allow_revoked=True)
                if previous_owner != owner or previous is None or previous['enabled']:
                    raise Conflict('Replacement history does not match')
                return {'replayed': True}
        owner, _ = check_record(store, db, old)
        if not resume:
            payload = {'version': 2, 'database': str(store.path.resolve()),
                       'command': str(uuid.uuid4()), 'capability': secrets.token_urlsafe(32),
                       'owner_hash': owner, 'previous_hash': old_hash}
            new = {**payload, 'mac': provision.credential_mac(store, payload)}
            data = encoded(new) + b'\n'
            if len(data) > provision.MAX_CREDENTIAL_BYTES:
                raise Invalid('Credential path exceeds supported size')
            # A publication failure leaves the old access valid. A complete new
            # file may exist; explicit resume safely reuses it after interruption.
            provision.publish_private(output, data)
        if new['owner_hash'] != owner or token_hash(new['capability']) == old_hash:
            raise Conflict('Replacement owner mismatch')
        if (access_row(store, db, token_hash(new['capability'])) is not None or
                db.execute('SELECT 1 FROM owners WHERE id=?', (token_hash(new['capability']),)).fetchone()):
            raise Conflict('Replacement capability already registered')
        db.execute('PRAGMA user_version=' + str(max(2, db.execute('PRAGMA user_version').fetchone()[0])))
        write_access(store, db, old, owner, False)
        write_access(store, db, new, owner, True)
    return {'replayed': False}


def revoke(store, credential_file):
    with store.transaction() as db:
        record = provision.read_credential(store, credential_file)
        owner, row = check_record(store, db, record, allow_revoked=True)
        if row is not None and not row['enabled']:
            return {'replayed': True}
        db.execute('PRAGMA user_version=' + str(max(2, db.execute('PRAGMA user_version').fetchone()[0])))
        write_access(store, db, record, owner, False)
    return {'replayed': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    for name in ('rotate', 'revoke'):
        command = actions.add_parser(name)
        command.add_argument('--database', type=Path, required=True)
        command.add_argument('--key-file', type=Path, required=True)
        command.add_argument('--credential-file', type=Path, required=True)
        if name == 'rotate':
            command.add_argument('--output', type=Path, required=True)
            command.add_argument('--resume', action='store_true')
    args = parser.parse_args(argv)
    try:
        store = provision.open_store(args.database, bytes.fromhex(read_secret(args.key_file)))
        if args.action == 'rotate':
            rotate(store, args.credential_file, args.output, resume=args.resume)
            print('Replacement access verified. Previous code is disabled; new code is in the private file only.')
        else:
            revoke(store, args.credential_file)
            print('Specified owner code is disabled. This does not cancel queued messages or revoke helper links.')
        print('No message sent. Account history preserved. Do not run older application versions.')
        return 0
    except Exception:
        print('Access change refused or interrupted. Preserve private files and inspect the exact store/key. '
              'For an interrupted rotation, use the same input/output with --resume. No credential printed.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
