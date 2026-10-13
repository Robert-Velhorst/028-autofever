"""Private, bounded encrypted snapshots and quarantined restore copies; no send/cutover."""

import argparse
import hashlib
import os
import re
import sqlite3
import stat
import struct
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from backend.dispatch_lock import delivery_lock
from backend.hosted import read_secret
from backend.service import Invalid, RecordCodec, SCHEMA, snapshot


MAGIC = b'AUTOFEVER-BACKUP\x01'
MAX_DATABASE_BYTES = 64 * 1024 * 1024
OVERHEAD = len(MAGIC) + 12 + 16 + 8
OPERATION_SECONDS = 30


def archive_cipher(key):
    if not isinstance(key, bytes) or len(key) != 32:
        raise Invalid('A 32-byte store key is required')
    material = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                    info=b'autofever:backup:v1').derive(key)
    return AESGCM(material)


def regular_file(path):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise Invalid('Use a regular, non-symlink, non-hardlinked file')
    return path


def readonly(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=1)
    db.execute('PRAGMA trusted_schema=OFF')
    db.execute('PRAGMA query_only=ON')
    return db


def schema_rows(db):
    return db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()


def check_identity(db, codec):
    if (db.execute('PRAGMA application_id').fetchone()[0] != 1095128625 or
            db.execute('PRAGMA user_version').fetchone()[0] != 1):
        raise Invalid('Unsupported service database')
    check = db.execute("SELECT value FROM metadata WHERE name='key-check'").fetchone()
    if check is None or codec.open('key-check', check[0]) != {'version': 1}:
        raise Invalid('Missing or invalid key check')


def validate_database(path, key):
    """Offline structural/authentication check, not proof of current provider state.

    Never initializes or repairs a database. Counts only are returned; neither
    raw capabilities nor decrypted personal records are printed by the CLI.
    """
    path = regular_file(path)
    if not 0 < path.stat().st_size <= MAX_DATABASE_BYTES:
        raise Invalid('Database is empty or exceeds the supported bound')
    codec = RecordCodec(key)
    deadline = time.monotonic() + OPERATION_SECONDS
    def budget():
        if time.monotonic() >= deadline:
            raise Invalid('Verification time limit reached')
    with closing(readonly(path)) as db, closing(sqlite3.connect(':memory:')) as expected:
        db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        check_identity(db, codec)
        expected.executescript(SCHEMA)
        if schema_rows(db) != schema_rows(expected):
            raise Invalid('Unexpected schema, missing index, trigger or view')
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise Invalid('Database integrity failed')
        if db.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise Invalid('Database relationships failed')
        checked, held = False, False
        for name, blob in db.execute('SELECT name,value FROM metadata'):
            budget()
            value = codec.open(name, blob)
            if name == 'key-check':
                if value != {'version': 1}:
                    raise Invalid('Invalid key check')
                checked = True
            elif name == 'restore-hold':
                if (not isinstance(value, dict) or set(value) !=
                        {'version', 'backup_created_at', 'restored_at', 'archive_sha256'} or
                        value['version'] != 1 or
                        any(type(value[k]) is not int or value[k] < 0
                            for k in ('backup_created_at', 'restored_at')) or
                        not isinstance(value['archive_sha256'], str) or
                        not re.fullmatch(r'[0-9a-f]{64}', value['archive_sha256'])):
                    raise Invalid('Invalid restore marker')
                held = True
            elif re.fullmatch(r'resolution:[A-Za-z0-9_-]+:[1-5]', name):
                if not isinstance(value, dict) or set(value) != {
                        'decision', 'attempt', 'outcome', 'retry', 'result', 'recorded_at'}:
                    raise Invalid('Invalid reconciliation record')
            elif re.fullmatch(r'provision:[0-9a-f-]{36}', name):
                if (not isinstance(value, dict) or set(value) !=
                        {'version', 'owner_hash', 'credential_digest', 'created_at'} or
                        type(value['version']) is not int or value['version'] != 1 or
                        type(value['created_at']) is not int or value['created_at'] < 0 or
                        any(not isinstance(value[k], str) or not re.fullmatch(r'[0-9a-f]{64}', value[k])
                            for k in ('owner_hash', 'credential_digest'))):
                    raise Invalid('Invalid owner enrollment record')
            else:
                raise Invalid('Unsupported metadata')
        if not checked:
            raise Invalid('Missing key check')
        for identity, blob in db.execute('SELECT id,data FROM episodes'):
            budget()
            snapshot(codec.open(identity, blob))
        for identity, episode, recipient, kind, blob, receipt in db.execute(
                'SELECT id,episode,recipient,kind,payload,receipt FROM jobs'):
            budget()
            value = codec.open(identity, blob)
            if (not isinstance(value, dict) or value.get('id') != identity or
                    value.get('idempotency_key') != identity or value.get('episode_id') != episode or
                    value.get('recipient_id') != recipient or value.get('kind') != kind):
                raise Invalid('Job envelope identity mismatch')
            if receipt is not None:
                value = codec.open(identity + ':receipt', receipt)
                if not isinstance(value, str) or not 1 <= len(value) <= 1000:
                    raise Invalid('Invalid receipt')
        counts = {name: db.execute('SELECT count(*) FROM ' + name).fetchone()[0]
                  for name in ('owners', 'episodes', 'recipients', 'tasks', 'declines', 'jobs')}
        budget()
        return {'counts': counts, 'restore_held': held}


def write_private(path, data):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'wb') as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def publish_new(stage, target):
    # Same-parent staging keeps this on one filesystem. link() is atomic and
    # refuses an existing target, unlike replace(). No partially written file
    # is ever published. Both links are harmless and fail closed after a crash.
    # Windows _commit requires a writable descriptor (the stage is ours).
    with open(stage, 'r+b') as stream:
        os.fsync(stream.fileno())
    os.link(stage, target)
    os.unlink(stage)
    if os.name == 'posix':
        fd = os.open(Path(target).parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def new_target(path):
    path = Path(path).absolute()
    if path.exists() or path.is_symlink() or not path.parent.is_dir():
        raise Invalid('Choose a new filename in an existing private directory')
    # Never publish next to stale SQLite sidecars from an earlier database.
    if any(Path(str(path) + suffix).exists() or Path(str(path) + suffix).is_symlink()
           for suffix in ('-wal', '-shm', '-journal', '.dispatch.lock')):
        raise Invalid('Target has existing database sidecars')
    return path


def create_backup(database, archive, key):
    """Consistent SQLite snapshot while excluding this version's live senders."""
    cipher = archive_cipher(key)
    source, target = regular_file(database), new_target(archive)
    # Refuse a foreign store/key before even creating its lock sidecar. The
    # copied snapshot is checked again; this is not the integrity verification.
    with closing(readonly(source)) as db:
        check_identity(db, RecordCodec(key))
    with delivery_lock(source), tempfile.TemporaryDirectory(prefix='.autofever-backup-', dir=target.parent) as tmp:
        # Conservative start of the snapshot interval, never a claimed exact
        # provider-history cutoff after copying/verification has finished.
        created = int(time.time())
        stage = Path(tmp) / 'snapshot.sqlite3'
        write_private(stage, b'')
        deadline = time.monotonic() + OPERATION_SECONDS
        with closing(readonly(source)) as src, closing(sqlite3.connect(stage)) as dst:
            page_size = src.execute('PRAGMA page_size').fetchone()[0]
            def progress(_status, _remaining, total):
                if total * page_size > MAX_DATABASE_BYTES or time.monotonic() >= deadline:
                    raise Invalid('Snapshot size or time limit reached')
            if src.execute('PRAGMA page_count').fetchone()[0] * page_size > MAX_DATABASE_BYTES:
                raise Invalid('Database exceeds the supported bound')
            src.backup(dst, pages=128, progress=progress, sleep=0.05)
            # A WAL source may copy its persistent journal mode. Normalize the
            # disposable snapshot before serializing the single complete file.
            dst.execute('PRAGMA journal_mode=DELETE')
        report = validate_database(stage, key)
        nonce = os.urandom(12)
        payload = struct.pack('>Q', created) + stage.read_bytes()
        sealed = MAGIC + nonce + cipher.encrypt(nonce, payload, MAGIC)
        ready = Path(tmp) / 'archive.afbackup'
        write_private(ready, sealed)
        publish_new(ready, target)
        return {**report, 'backup_created_at': created}


def read_archive(archive, key):
    path = regular_file(archive)
    with path.open('rb') as stream:
        sealed = stream.read(MAX_DATABASE_BYTES + OVERHEAD + 1)
    if not OVERHEAD < len(sealed) <= MAX_DATABASE_BYTES + OVERHEAD or not sealed.startswith(MAGIC):
        raise Invalid('Unsupported, truncated or oversized backup')
    nonce = sealed[len(MAGIC):len(MAGIC) + 12]
    payload = archive_cipher(key).decrypt(nonce, sealed[len(MAGIC) + 12:], MAGIC)
    created = struct.unpack('>Q', payload[:8])[0]
    return payload[8:], created, hashlib.sha256(sealed).hexdigest()


def verify_backup(archive, key, *, work_directory):
    """Decrypt into a private temporary directory, validate and remove that copy."""
    data, created, _digest = read_archive(archive, key)
    with tempfile.TemporaryDirectory(prefix='.autofever-verify-', dir=work_directory) as tmp:
        stage = Path(tmp) / 'snapshot.sqlite3'
        write_private(stage, data)
        return {**validate_database(stage, key), 'backup_created_at': created}


def restore_copy(archive, database, key):
    """Restore to a NEW path with an authenticated, persistent application hold.

    There is deliberately no release-hold switch: post-snapshot provider history,
    missing episodes and revoked capabilities require a separate cutover design.
    """
    target = new_target(database)
    data, created, digest = read_archive(archive, key)
    with tempfile.TemporaryDirectory(prefix='.autofever-restore-', dir=target.parent) as tmp:
        stage = Path(tmp) / 'restored.sqlite3'
        write_private(stage, data)
        report = validate_database(stage, key)
        codec = RecordCodec(key)
        hold = {'version': 1, 'backup_created_at': created, 'restored_at': int(time.time()), 'archive_sha256': digest}
        with closing(sqlite3.connect(stage)) as db:
            db.execute('PRAGMA synchronous=FULL')
            # Keep the first hold/provenance if this is already a held backup.
            db.execute('INSERT OR IGNORE INTO metadata VALUES (?,?)', ('restore-hold', codec.seal('restore-hold', hold)))
            db.commit()
        checked = validate_database(stage, key)
        if not checked['restore_held'] or checked['counts'] != report['counts']:
            raise Invalid('Restore verification failed')
        publish_new(stage, target)
        return {**checked, 'backup_created_at': created}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key-file', type=Path, required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('create', help='Create a new encrypted archive; never replace an existing file')
    create.add_argument('--database', type=Path, required=True)
    create.add_argument('--archive', type=Path, required=True)
    verify = commands.add_parser('verify', help='Verify in a private temporary working directory')
    verify.add_argument('--archive', type=Path, required=True)
    verify.add_argument('--work-directory', type=Path, required=True)
    restore = commands.add_parser('restore-copy', help='Restore a NEW, blocked review copy; not a live cutover')
    restore.add_argument('--archive', type=Path, required=True)
    restore.add_argument('--database', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        key = bytes.fromhex(read_secret(args.key_file))
        if args.command == 'create':
            create_backup(args.database, args.archive, key)
            print('Encrypted backup created. Keep its key separately; verify a restore copy before relying on it.')
        elif args.command == 'verify':
            report = verify_backup(args.archive, key, work_directory=args.work_directory)
            print('Backup integrity and record authentication verified. No live delivery or cutover was verified.')
            print('Snapshot contains restore hold: ' + ('yes' if report['restore_held'] else 'no'))
        else:
            restore_copy(args.archive, args.database, key)
            print('Quarantined restore copy created. Application access and sending are blocked; no cutover performed.')
        return 0
    except Exception:
        print('Backup operation refused or interrupted. Check private paths, key, integrity, limits and active sender. '
              'Inspect any existing output before retrying; no file is overwritten.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
