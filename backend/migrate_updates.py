"""Explicit forward-only v1/v2 -> v3 queue migration after an encrypted backup.

Stop all Autofever processes first. Never points at Hire.ai state or sends mail.
"""
import argparse
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from backend import backup, provision
from backend.dispatch_lock import delivery_lock
from backend.hosted import read_secret
from backend.service import Conflict, Invalid, SCHEMA, SCHEMA_V3


def migrate(database, key, backup_output):
    backup.new_target(backup_output)
    store = provision.open_store(database, key)
    # This is a separate transaction from DDL. No change if backup fails. The
    # operator must stop application processes; backup is not a rollback switch.
    backup.create_backup(database, backup_output, key)
    with delivery_lock(store.path, timeout=10), store.transaction() as db:
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version == 3:
            return {'migrated': False}
        if version not in (1, 2):
            raise Invalid('Unsupported source version')
        if db.execute("SELECT 1 FROM jobs WHERE status='sending'").fetchone():
            raise Conflict('Resolve in-flight sends before migration')
        with closing(sqlite3.connect(':memory:')) as expected:
            expected.executescript(SCHEMA)
            actual = [tuple(r) for r in db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name')]
            if actual != backup.schema_rows(expected):
                raise Invalid('Source schema differs from the supported version')
        db.execute('ALTER TABLE jobs RENAME TO jobs_before_updates')
        create_jobs = next(s for s in SCHEMA_V3.split(';') if 'CREATE TABLE IF NOT EXISTS jobs (' in s)
        db.execute(create_jobs)
        db.execute('INSERT INTO jobs(id,episode,recipient,kind,payload,status,attempts,due,lease,receipt) '
                   'SELECT id,episode,recipient,kind,payload,status,attempts,due,lease,receipt FROM jobs_before_updates ORDER BY rowid')
        columns = 'id,episode,recipient,kind,payload,status,attempts,due,lease,receipt'
        if (db.execute('SELECT ' + columns + ' FROM jobs EXCEPT SELECT ' + columns + ' FROM jobs_before_updates').fetchone() or
                db.execute('SELECT ' + columns + ' FROM jobs_before_updates EXCEPT SELECT ' + columns + ' FROM jobs').fetchone()):
            raise Invalid('Migration did not preserve all job content')
        db.execute('DROP TABLE jobs_before_updates')
        db.execute('CREATE INDEX IF NOT EXISTS due_jobs ON jobs(status,due)')
        with closing(sqlite3.connect(':memory:')) as expected:
            expected.executescript(SCHEMA_V3)
            actual = [tuple(r) for r in db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name')]
            if actual != backup.schema_rows(expected):
                raise Invalid('Migration target schema validation failed')
        db.execute('PRAGMA user_version=3')
        if db.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise Invalid('Migration relationship validation failed')
    backup.validate_database(database, key)
    return {'migrated': True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--backup-output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = migrate(args.database, bytes.fromhex(read_secret(args.key_file)), args.backup_output)
        print('Updates migration committed.' if result['migrated'] else 'Already at updates version; fresh backup created.')
        print('Preserve the backup. Run only v3-aware Autofever processes; no messages sent.')
        return 0
    except Exception:
        print('Migration refused or interrupted. Preserve all files and check the current database version and backup privately. '
              'Do not downgrade or overwrite state. No credentials printed.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
