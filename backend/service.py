"""Transactional illness/help lifecycle; trusted in-process boundary, not a public API.

Owner capabilities must be provisioned by a trusted caller. Recipient capabilities
only permit that recipient's view and actions. No provider is selected implicitly.
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from backend.profile import compile_profile
from backend.dispatch_lock import DeliveryBusy, delivery_lock


class Invalid(ValueError):
    pass


class Denied(Exception):
    """Use the same outward error for missing, expired and unauthorized objects."""


class Conflict(Exception):
    pass


class RestoreHeld(RuntimeError):
    """A recovered database is evidence to review, not a live application store."""


class SendFailure(Exception):
    """Only use retryable/permanent when the provider definitely did not accept.

    Timeouts, connection loss after submitting, and unknown errors are uncertain.
    Provider exception messages are never persisted or exposed to recipients.
    """

    def __init__(self, outcome):
        if outcome not in {'retryable', 'permanent', 'uncertain'}:
            raise Invalid('Unknown send outcome')
        self.outcome = outcome


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def token_hash(token):
    if not isinstance(token, str) or not 32 <= len(token) <= 128:
        raise Denied('Unavailable')
    return hashlib.sha256(token.encode()).hexdigest()


def validate_access(value):
    if (not isinstance(value, dict) or set(value) !=
            {'version', 'owner_hash', 'enabled', 'credential_digest', 'created_at'} or
            type(value['version']) is not int or value['version'] != 1 or
            type(value['enabled']) is not bool or
            type(value['created_at']) is not int or value['created_at'] < 0 or
            any(not isinstance(value[k], str) or not re.fullmatch(r'[0-9a-f]{64}', value[k])
                for k in ('owner_hash', 'credential_digest'))):
        raise Invalid('Invalid owner access record')
    return value


def text(value, maximum, *, identifier=False):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or '\x00' in value:
        raise Invalid('Invalid text')
    if identifier and not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise Invalid('Invalid identifier')
    return value


def snapshot(value):
    if not isinstance(value, dict) or set(value) not in ({'recipients', 'tasks'}, {'recipients', 'tasks', 'preparation'}):
        raise Invalid('Expected recipients and tasks')
    if 'preparation' in value:
        try:
            prepared = value['preparation']
            if not isinstance(prepared, dict) or set(prepared) != {'profile', 'contacts'}:
                raise ValueError('Invalid preparation')
            if compile_profile(prepared['profile'], prepared['contacts']) != value:
                raise ValueError('Snapshot differs from saved profile')
        except ValueError as error:
            raise Invalid('Invalid saved profile') from error
    recipients, tasks = value['recipients'], value['tasks']
    if not isinstance(recipients, list) or not 1 <= len(recipients) <= 100:
        raise Invalid('Expected 1 to 100 recipients')
    if not isinstance(tasks, list) or len(tasks) > 100:
        raise Invalid('Too many tasks')
    seen = set()
    for item in recipients:
        if not isinstance(item, dict) or set(item) != {'id', 'channel', 'destination', 'message'}:
            raise Invalid('Invalid recipient fields')
        rid = text(item['id'], 80, identifier=True)
        if rid in seen:
            raise Invalid('Duplicate recipient')
        seen.add(rid)
        if item['channel'] not in ('email', 'sms', 'whatsapp', 'push'):
            raise Invalid('Unsupported channel')
        destination = text(item['destination'], 320)
        if any(ord(c) < 32 or ord(c) == 127 for c in destination):
            raise Invalid('Invalid destination')
        if item['channel'] == 'email' and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', destination):
            raise Invalid('Invalid email')
        if item['channel'] in ('sms', 'whatsapp') and not re.fullmatch(r'\+[1-9][0-9]{6,14}', destination):
            raise Invalid('Expected international phone number')
        text(item['message'], 10000)
    task_ids = set()
    for task in tasks:
        if not isinstance(task, dict) or set(task) not in ({'id', 'title', 'timing', 'assignees'}, {'id', 'title', 'description', 'timing', 'assignees'}):
            raise Invalid('Invalid task fields')
        tid = text(task['id'], 80, identifier=True)
        if tid in task_ids:
            raise Invalid('Duplicate task')
        task_ids.add(tid)
        text(task['title'], 1000)
        text(task['timing'], 1000)
        if 'description' in task and (not isinstance(task['description'], str) or len(task['description']) > 2000 or '\x00' in task['description']):
            raise Invalid('Invalid task description')
        helpers = task['assignees']
        if (not isinstance(helpers, list) or not helpers or
                any(not isinstance(x, str) for x in helpers) or
                len(set(helpers)) != len(helpers) or not set(helpers) <= seen):
            raise Invalid('Invalid task helpers')
    return json.loads(encoded(value))  # Deep copy; caller edits cannot change an active plan.


SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS owners (id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS episodes (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES owners(id),
 command TEXT NOT NULL, digest TEXT NOT NULL, data BLOB NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('active','recovered','cancelled')),
 created INTEGER NOT NULL, UNIQUE(owner, command));
CREATE UNIQUE INDEX IF NOT EXISTS one_active ON episodes(owner) WHERE state='active';
CREATE TABLE IF NOT EXISTS recipients (
 token TEXT PRIMARY KEY, episode TEXT NOT NULL REFERENCES episodes(id),
 recipient TEXT NOT NULL, expires INTEGER NOT NULL, acknowledged INTEGER NOT NULL DEFAULT 0,
 UNIQUE(episode, recipient));
CREATE TABLE IF NOT EXISTS tasks (
 episode TEXT NOT NULL REFERENCES episodes(id), id TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('pending','accepted','completed','closed')),
 claimant TEXT, PRIMARY KEY(episode, id));
CREATE TABLE IF NOT EXISTS declines (
 episode TEXT NOT NULL, task TEXT NOT NULL, recipient TEXT NOT NULL,
 PRIMARY KEY(episode, task, recipient), FOREIGN KEY(episode, task) REFERENCES tasks(episode,id));
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, episode TEXT NOT NULL REFERENCES episodes(id),
 recipient TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('illness','recovery')),
 payload BLOB NOT NULL, status TEXT NOT NULL CHECK(status IN
 ('queued','sending','accepted','failed','uncertain','cancelled')),
 attempts INTEGER NOT NULL DEFAULT 0, due INTEGER NOT NULL, lease INTEGER,
 receipt BLOB, UNIQUE(episode,recipient,kind));
CREATE INDEX IF NOT EXISTS due_jobs ON jobs(status,due);
"""

# Legacy schema stays frozen for backup validation and explicit v3 migration.
SCHEMA_V3 = SCHEMA.replace("kind IN ('illness','recovery')", "kind IN ('illness','recovery','update')").replace(
    'receipt BLOB, UNIQUE(episode,recipient,kind)',
    "receipt BLOB, batch TEXT NOT NULL DEFAULT '', UNIQUE(episode,recipient,kind,batch)")


def validate_update(value):
    if (not isinstance(value, dict) or set(value) != {'version', 'command', 'message', 'recipients', 'created_at'} or
            type(value['version']) is not int or value['version'] != 1 or
            type(value['created_at']) is not int or value['created_at'] < 0):
        raise Invalid('Invalid update record')
    text(value['command'], 128, identifier=True)
    text(value['message'], 2000)
    recipients = value['recipients']
    if not isinstance(recipients, list) or not 1 <= len(recipients) <= 100:
        raise Invalid('Choose update recipients')
    for recipient in recipients:
        text(recipient, 80, identifier=True)
    if len(set(recipients)) != len(recipients):
        raise Invalid('Duplicate update recipients')
    return value


def validate_checkin_record(value):
    if (not isinstance(value, dict) or set(value) != {'version', 'command', 'confirmed_at'} or
            type(value['version']) is not int or value['version'] != 1 or
            type(value['confirmed_at']) is not int or value['confirmed_at'] < 0):
        raise Invalid('Invalid check-in record')
    text(value['command'], 128, identifier=True)
    return value


def validate_retention_record(value):
    if (not isinstance(value, dict) or set(value) != {'version', 'retention_days'} or
            type(value['version']) is not int or value['version'] != 1 or
            (value['retention_days'] is not None and
             (type(value['retention_days']) is not int or not 1 <= value['retention_days'] <= 3650))):
        raise Invalid('Invalid retention policy')
    return value


def validate_closure_record(value):
    if (not isinstance(value, dict) or set(value) != {'version', 'closed_at'} or
            type(value['version']) is not int or value['version'] != 1 or
            type(value['closed_at']) is not int or value['closed_at'] < 0):
        raise Invalid('Invalid episode closure record')
    return value


class RecordCodec:
    """Record encryption shared by the live store and offline backup verifier."""

    def __init__(self, key):
        if not isinstance(key, bytes) or len(key) != 32:
            raise Invalid('Supply a 32-byte key from private operator configuration')
        material = HKDF(algorithm=hashes.SHA256(), length=64, salt=None,
                        info=b'autofever:service:v1').derive(key)
        self.key, self.cipher = material[32:], AESGCM(material[:32])

    def seal(self, identity, value):
        nonce = os.urandom(12)
        return nonce + self.cipher.encrypt(nonce, encoded(value), ('autofever:v1:' + identity).encode())

    def open(self, identity, value):
        return json.loads(self.cipher.decrypt(value[:12], value[12:], ('autofever:v1:' + identity).encode()))


class Store(RecordCodec):
    def __init__(self, path, key, *, clock=time.time):
        super().__init__(key)
        self.path, self.clock = Path(path), clock
        if self.path.is_symlink():
            raise Invalid('Symlink database refused')
        if not self.path.exists():
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        with self.transaction() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            application = db.execute('PRAGMA application_id').fetchone()[0]
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
            if (tables or version or application) and (application != 1095128625 or version not in (1, 2, 3)):
                raise Invalid('Not an Autofever service database')
            if version in (1, 2, 3) and {x[0] for x in tables} != {'metadata', 'owners', 'episodes', 'recipients', 'tasks', 'declines', 'jobs'}:
                raise Invalid('Incomplete service database; restore rather than silently recreate tables')
            if version not in (0, 1, 2, 3):
                raise Invalid('Unsupported database version')
            for statement in (SCHEMA_V3 if version in (0, 3) else SCHEMA).split(';'):
                if statement.strip():
                    db.execute(statement)
            check = db.execute("SELECT value FROM metadata WHERE name='key-check'").fetchone()
            if check is None:
                if version in (1, 2, 3):
                    raise Invalid('Missing database key check')
                db.execute('INSERT INTO metadata VALUES (?,?)', ('key-check', self.seal('key-check', {'version': 1})))
            elif self.open('key-check', check[0]) != {'version': 1}:
                raise Invalid('Invalid database key')
            db.execute('PRAGMA user_version=' + str(version or 3))
            db.execute('PRAGMA application_id=1095128625')

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            # Also reject unsupported versions on already-running Store objects.
            # Every reader/writer must honor access revocation, not just startup.
            if db.execute('PRAGMA user_version').fetchone()[0] not in (0, 1, 2, 3):
                raise Invalid('Unsupported database version')
            # Checked on every transaction, including startup and read routes.
            # Presence alone blocks use even if the marker is damaged. An old
            # snapshot may contain valid but subsequently revoked capabilities.
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'").fetchone():
                if db.execute("SELECT 1 FROM metadata WHERE name='restore-hold'").fetchone():
                    raise RestoreHeld('Restored copy requires offline operator review')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def create_owner(self):
        """Trusted provisioning only; never expose as an unauthenticated public endpoint."""
        token = secrets.token_urlsafe(32)
        with self.transaction() as db:
            db.execute('INSERT INTO owners VALUES (?)', (token_hash(token),))
        return token

    def _owner(self, db, token):
        owner = token_hash(token)
        identity = 'owner-access:' + owner
        row = db.execute('SELECT value FROM metadata WHERE name=?', (identity,)).fetchone()
        if row is not None:
            access = validate_access(self.open(identity, row['value']))
            if not access['enabled']:
                raise Denied('Unavailable')
            owner = access['owner_hash']
        if not db.execute('SELECT 1 FROM owners WHERE id=?', (owner,)).fetchone():
            raise Denied('Unavailable')
        return owner

    def _episode(self, db, owner_token, eid):
        owner = self._owner(db, owner_token)
        row = db.execute('SELECT * FROM episodes WHERE id=? AND owner=?', (eid, owner)).fetchone()
        if row is None:
            raise Denied('Unavailable')
        return row

    def activate(self, owner_token, command, value, *, link_ttl):
        text(command, 128, identifier=True)
        value = snapshot(value)
        if type(link_ttl) is not int or not 60 <= link_ttl <= 7 * 86400:
            raise Invalid('Choose an explicit link lifetime between 60 seconds and 7 days')
        digest = hmac.new(self.key, encoded([value, link_ttl]), hashlib.sha256).hexdigest()
        now = int(self.clock())
        with self.transaction() as db:
            owner = self._owner(db, owner_token)
            existing = db.execute('SELECT id,digest FROM episodes WHERE owner=? AND command=?', (owner, command)).fetchone()
            if existing:
                if not hmac.compare_digest(existing['digest'], digest):
                    raise Conflict('Activation key reused with different content')
                return existing['id']
            if db.execute("SELECT 1 FROM episodes WHERE owner=? AND state='active'", (owner,)).fetchone():
                raise Conflict('An episode is already active')
            if db.execute("SELECT 1 FROM jobs j JOIN episodes e ON e.id=j.episode WHERE e.owner=? "
                          "AND j.status IN ('queued','sending','uncertain')", (owner,)).fetchone():
                raise Conflict('Previous notifications must finish or be reconciled before a new episode')
            eid = str(uuid.uuid4())
            db.execute('INSERT INTO episodes VALUES (?,?,?,?,?,?,?)',
                       (eid, owner, command, digest, self.seal(eid, value), 'active', now))
            for recipient in value['recipients']:
                token = secrets.token_urlsafe(32)
                db.execute('INSERT INTO recipients(token,episode,recipient,expires) VALUES (?,?,?,?)',
                           (token_hash(token), eid, recipient['id'], now + link_ttl))
                self._job(db, eid, recipient, 'illness', now, action_token=token)
            for task in value['tasks']:
                db.execute('INSERT INTO tasks(episode,id,state,claimant) VALUES (?,?,?,NULL)', (eid, task['id'], 'pending'))
            return eid

    def _job(self, db, eid, recipient, kind, now, *, batch='', **extra):
        jid = str(uuid.uuid4())
        envelope = {**recipient, 'id': jid, 'recipient_id': recipient['id'], 'episode_id': eid, 'kind': kind,
                    'idempotency_key': jid, **extra}
        columns = 'id,episode,recipient,kind,payload,status,due'
        values = (jid, eid, recipient['id'], kind, self.seal(jid, envelope), 'queued', now)
        if batch:
            columns += ',batch'
            values += (batch,)
        db.execute('INSERT INTO jobs(' + columns + ') VALUES (' + ','.join('?' for _ in values) + ')', values)

    def updates(self, db, eid):
        return [validate_update(self.open(r['name'], r['value'])) for r in
                db.execute('SELECT name,value FROM metadata WHERE name LIKE ? ORDER BY rowid', ('update:' + eid + ':%',))]

    def update(self, owner_token, eid, command, message, recipients):
        record = validate_update({'version': 1, 'command': command, 'message': message,
                                  'recipients': recipients, 'created_at': int(self.clock())})
        record['recipients'] = sorted(recipients)
        recipients = record['recipients']  # Freeze the caller's mutable selection.
        with self.transaction() as db:
            row = self._episode(db, owner_token, eid)
            identity = 'update:' + eid + ':' + command
            prior = db.execute('SELECT value FROM metadata WHERE name=?', (identity,)).fetchone()
            if prior:
                previous = validate_update(self.open(identity, prior['value']))
                if previous['message'] != message or previous['recipients'] != record['recipients']:
                    raise Conflict('Update command reused with different content')
                return
            if db.execute('PRAGMA user_version').fetchone()[0] != 3:
                raise Conflict('Operator must run the backed-up updates migration first')
            if row['state'] != 'active':
                raise Conflict('Episode is closed')
            informed = {r[0] for r in db.execute("SELECT recipient FROM jobs WHERE episode=? AND kind='illness' AND status='accepted'", (eid,))}
            if not set(recipients) <= informed:
                raise Conflict('Update recipients must have an accepted initial notification')
            if len(self.updates(db, eid)) >= 50:
                raise Conflict('Episode update limit reached')
            if db.execute("SELECT 1 FROM jobs WHERE episode=? AND kind='update' AND status IN ('queued','sending','uncertain')", (eid,)).fetchone():
                raise Conflict('Finish or reconcile the previous update first')
            value = self.open(eid, row['data'])
            for recipient in value['recipients']:
                if recipient['id'] in recipients:
                    self._job(db, eid, {**recipient, 'message': message}, 'update', record['created_at'], batch=command, update_command=command)
            db.execute('INSERT INTO metadata VALUES (?,?)', (identity, self.seal(identity, record)))

    def _episode_view(self, db, row, *, include_closed_checkin=False):
        eid = row['id']
        jobs = db.execute('SELECT id,recipient,kind,status,attempts FROM jobs WHERE episode=? ORDER BY rowid', (eid,)).fetchall()
        recipients = db.execute('SELECT recipient,acknowledged FROM recipients WHERE episode=? ORDER BY rowid', (eid,)).fetchall()
        tasks = db.execute('SELECT id,state,claimant FROM tasks WHERE episode=? ORDER BY rowid', (eid,)).fetchall()
        declines = db.execute('SELECT task,recipient FROM declines WHERE episode=?', (eid,)).fetchall()
        recovery = None
        if row['state'] == 'recovered':
            recovery_jobs = db.execute("SELECT id,recipient,payload FROM jobs WHERE episode=? AND kind='recovery' ORDER BY rowid", (eid,)).fetchall()
            for job in recovery_jobs:
                envelope = self.open(job['id'], job['payload'])
                if (not isinstance(envelope, dict) or envelope.get('id') != job['id'] or
                        envelope.get('episode_id') != eid or envelope.get('recipient_id') != job['recipient'] or
                        envelope.get('kind') != 'recovery' or not isinstance(envelope.get('message'), str) or
                        not envelope['message'].strip()):
                    raise Invalid('Invalid encrypted recovery job')
                if recovery is None:
                    recovery = {'message': envelope['message'], 'recipients': []}
                elif recovery['message'] != envelope['message']:
                    raise Invalid('Recovery jobs disagree on the message')
                recovery['recipients'].append(job['recipient'])
        value = self.open(eid, row['data'])
        checkin = None
        prepared = value.get('preparation', {}).get('profile')
        if prepared and (row['state'] == 'active' or include_closed_checkin):
            identity = 'checkin:' + eid
            saved = db.execute('SELECT value FROM metadata WHERE name=?', (identity,)).fetchone()
            confirmed = self.open(identity, saved['value']) if saved else None
            if confirmed is not None:
                validate_checkin_record(confirmed)
            last = confirmed['confirmed_at'] if confirmed else row['created']
            interval = prepared['checkin'] * 3600
            due = last + interval
            checkin = {'interval_hours': prepared['checkin'],
                       'last_confirmed_at': confirmed['confirmed_at'] if confirmed else None,
                       'next_due_at': due, 'due': row['state'] == 'active' and int(self.clock()) >= due}
        return {'id': eid, 'state': row['state'], 'checkin': checkin, 'recovery': recovery, 'notifications': [dict(x) for x in jobs],
                'updates': self.updates(db, eid), 'snapshot': value,
                'recipients': [{'id': r['recipient'], 'acknowledged': bool(r['acknowledged'])} for r in recipients],
                'tasks': [{**dict(t), 'declined_by': [d['recipient'] for d in declines if d['task'] == t['id']]} for t in tasks]}

    def episode(self, owner_token, eid):
        with self.transaction() as db:
            return self._episode_view(db, self._episode(db, owner_token, eid))

    def latest_episode(self, owner_token):
        with self.transaction() as db:
            owner = self._owner(db, owner_token)
            row = db.execute('SELECT id FROM episodes WHERE owner=? ORDER BY created DESC,rowid DESC LIMIT 1', (owner,)).fetchone()
        return self.episode(owner_token, row['id']) if row else None

    def export_owner(self, owner_token):
        """Return the authenticated owner's complete server-side episode history."""
        with self.transaction() as db:
            owner = self._owner(db, owner_token)
            rows = db.execute('SELECT * FROM episodes WHERE owner=? ORDER BY created,rowid', (owner,)).fetchall()
            return {'format': 'autofever-owner-export', 'version': 1, 'exported_at': int(self.clock()),
                    'episodes': [{'created_at': row['created'],
                                  **self._episode_view(db, row, include_closed_checkin=True)} for row in rows]}

    def retention_days(self, owner_token):
        with self.transaction() as db:
            owner = self._owner(db, owner_token)
            identity = 'retention:' + owner
            row = db.execute('SELECT value FROM metadata WHERE name=?', (identity,)).fetchone()
            if row is None:
                return None
            return validate_retention_record(self.open(identity, row['value']))['retention_days']

    def set_retention_days(self, owner_token, days):
        validate_retention_record({'version': 1, 'retention_days': days})
        with self.transaction() as db:
            owner = self._owner(db, owner_token)
            identity = 'retention:' + owner
            if days is None:
                db.execute('DELETE FROM metadata WHERE name=?', (identity,))
            else:
                db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',
                           (identity, self.seal(identity, {'version': 1, 'retention_days': days})))
        return days

    def purge_expired_history(self, *, limit=100):
        """Delete only opted-in, old, closed episodes without pending send outcomes.

        The shared delivery lock excludes dispatch/reconciliation for the full
        operation. A bounded batch keeps the SQLite write transaction short;
        repeated scheduled runs safely catch up after a backlog.
        """
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise Invalid('Choose a bounded retention batch between 1 and 1000')
        try:
            with delivery_lock(self.path, timeout=0):
                with self.transaction() as db:
                    now = int(self.clock())
                    policies = db.execute("SELECT name,value FROM metadata WHERE name LIKE 'retention:%'").fetchall()
                    eligible = []
                    for policy in policies:
                        owner = policy['name'].split(':', 1)[1]
                        if not re.fullmatch(r'[0-9a-f]{64}', owner) or not db.execute('SELECT 1 FROM owners WHERE id=?', (owner,)).fetchone():
                            raise Invalid('Invalid retention owner binding')
                        days = validate_retention_record(self.open(policy['name'], policy['value']))['retention_days']
                        if days is None:
                            continue
                        cutoff = now - days * 86400
                        episodes = db.execute(
                            "SELECT id FROM episodes WHERE owner=? AND state IN ('recovered','cancelled') ORDER BY rowid",
                            (owner,))
                        for episode in episodes:
                            eid = episode['id']
                            closure_identity = 'closure:' + eid
                            closure = db.execute('SELECT value FROM metadata WHERE name=?', (closure_identity,)).fetchone()
                            if closure is None:
                                # Legacy closed events have no trustworthy closure timestamp.
                                continue
                            closed_at = validate_closure_record(self.open(closure_identity, closure['value']))['closed_at']
                            if closed_at > cutoff:
                                continue
                            unresolved = db.execute(
                                "SELECT 1 FROM jobs WHERE episode=? AND status IN ('queued','sending','uncertain') LIMIT 1",
                                (eid,)).fetchone()
                            if unresolved:
                                continue
                            eligible.append(eid)
                            if len(eligible) >= limit:
                                break
                        if len(eligible) >= limit:
                            break
                    for eid in eligible:
                        job_ids = [row['id'] for row in db.execute('SELECT id FROM jobs WHERE episode=?', (eid,)).fetchall()]
                        db.execute('DELETE FROM metadata WHERE name=?', ('closure:' + eid,))
                        db.execute('DELETE FROM metadata WHERE name=?', ('checkin:' + eid,))
                        db.execute('DELETE FROM metadata WHERE name LIKE ?', ('update:' + eid + ':%',))
                        for jid in job_ids:
                            db.execute('DELETE FROM metadata WHERE name LIKE ?', ('resolution:' + jid + ':%',))
                        db.execute('DELETE FROM declines WHERE episode=?', (eid,))
                        db.execute('DELETE FROM tasks WHERE episode=?', (eid,))
                        db.execute('DELETE FROM recipients WHERE episode=?', (eid,))
                        db.execute('DELETE FROM jobs WHERE episode=?', (eid,))
                        db.execute('DELETE FROM episodes WHERE id=?', (eid,))
                    return len(eligible)
        except DeliveryBusy as error:
            raise Conflict('Delivery or reconciliation is active; retry retention later') from error

    def delete_owner_data(self, owner_token):
        """Remove all live episode data for this owner without removing their access."""
        try:
            # Serialize against workers and operator reconciliation for the full
            # deletion transaction, so no provider call can begin after the wipe.
            with delivery_lock(self.path, timeout=0):
                with self.transaction() as db:
                    owner = self._owner(db, owner_token)
                    unresolved = db.execute(
                        "SELECT 1 FROM jobs j JOIN episodes e ON e.id=j.episode "
                        "WHERE e.owner=? AND j.status IN ('sending','uncertain') LIMIT 1", (owner,)).fetchone()
                    if unresolved:
                        raise Conflict('Resolve all sending or uncertain provider outcomes before deleting')
                    episodes = [row['id'] for row in db.execute(
                        'SELECT id FROM episodes WHERE owner=? ORDER BY rowid', (owner,)).fetchall()]
                    job_ids = [row['id'] for row in db.execute(
                        'SELECT j.id FROM jobs j JOIN episodes e ON e.id=j.episode WHERE e.owner=?',
                        (owner,)).fetchall()]
                    for eid in episodes:
                        db.execute('DELETE FROM metadata WHERE name=?', ('closure:' + eid,))
                        db.execute('DELETE FROM metadata WHERE name=?', ('checkin:' + eid,))
                        db.execute('DELETE FROM metadata WHERE name LIKE ?', ('update:' + eid + ':%',))
                    for jid in job_ids:
                        db.execute('DELETE FROM metadata WHERE name LIKE ?', ('resolution:' + jid + ':%',))
                    for eid in episodes:
                        db.execute('DELETE FROM declines WHERE episode=?', (eid,))
                        db.execute('DELETE FROM tasks WHERE episode=?', (eid,))
                        db.execute('DELETE FROM recipients WHERE episode=?', (eid,))
                        db.execute('DELETE FROM jobs WHERE episode=?', (eid,))
                        db.execute('DELETE FROM episodes WHERE id=? AND owner=?', (eid, owner))
                    return len(episodes)
        except DeliveryBusy as error:
            raise Conflict('A provider send is active; retry deletion after it finishes') from error

    def activate_profile(self, owner_token, command, profile, contacts, *, link_ttl):
        try:
            value = compile_profile(profile, contacts)
        except ValueError as error:
            raise Invalid('Invalid saved profile') from error
        return self.activate(owner_token, command, value, link_ttl=link_ttl)

    def confirm_checkin(self, owner_token, eid, command):
        text(command, 128, identifier=True)
        with self.transaction() as db:
            row = self._episode(db, owner_token, eid)
            if row['state'] != 'active':
                raise Conflict('Episode is closed')
            value = self.open(eid, row['data'])
            prepared = value.get('preparation', {}).get('profile')
            if not prepared:
                raise Conflict('No check-in preference is saved')
            identity = 'checkin:' + eid
            saved = db.execute('SELECT value FROM metadata WHERE name=?', (identity,)).fetchone()
            confirmed = self.open(identity, saved['value']) if saved else None
            if confirmed is not None:
                validate_checkin_record(confirmed)
            if confirmed and confirmed['command'] == command:
                return
            now = int(self.clock())
            interval = prepared['checkin'] * 3600
            last = confirmed['confirmed_at'] if confirmed else row['created']
            if now < last + interval:
                raise Conflict('Check-in is not due yet')
            record = {'version': 1, 'command': command, 'confirmed_at': now}
            sealed = self.seal(identity, record)
            if saved:
                db.execute('UPDATE metadata SET value=? WHERE name=?', (sealed, identity))
            else:
                db.execute('INSERT INTO metadata VALUES (?,?)', (identity, sealed))

    def _capability(self, db, token):
        row = db.execute("SELECT r.*, e.data FROM recipients r JOIN episodes e ON e.id=r.episode "
                         "WHERE r.token=? AND r.expires>? AND e.state='active'", (token_hash(token), int(self.clock()))).fetchone()
        if row is None:
            raise Denied('Unavailable')
        return row, self.open(row['episode'], row['data'])

    def recipient(self, token):
        with self.transaction() as db:
            row, value = self._capability(db, token)
            own = next(x for x in value['recipients'] if x['id'] == row['recipient'])
            tasks = []
            for task in value['tasks']:
                if row['recipient'] not in task['assignees']:
                    continue
                state = db.execute('SELECT state,claimant FROM tasks WHERE episode=? AND id=?', (row['episode'], task['id'])).fetchone()
                declined = db.execute('SELECT 1 FROM declines WHERE episode=? AND task=? AND recipient=?',
                                      (row['episode'], task['id'], row['recipient'])).fetchone()
                tasks.append({'id': task['id'], 'title': task['title'], 'timing': task['timing'],
                              **({'description': task['description']} if 'description' in task else {}),
                              'status': state['state'], 'claimed_by_you': state['claimant'] == row['recipient'],
                              'declined_by_you': bool(declined)})
            updates = [{'message': u['message'], 'created_at': u['created_at']} for u in self.updates(db, row['episode'])
                       if row['recipient'] in u['recipients']]
            return {'message': own['message'], 'acknowledged': bool(row['acknowledged']), 'tasks': tasks, 'updates': updates}

    def acknowledge(self, token):
        with self.transaction() as db:
            row, _ = self._capability(db, token)
            db.execute('UPDATE recipients SET acknowledged=1 WHERE token=?', (row['token'],))

    def respond(self, token, tid, action):
        if action not in ('accept', 'decline', 'complete'):
            raise Invalid('Unknown response')
        with self.transaction() as db:
            row, value = self._capability(db, token)
            task = next((x for x in value['tasks'] if x['id'] == tid and row['recipient'] in x['assignees']), None)
            if task is None:
                raise Denied('Unavailable')
            state = db.execute('SELECT state,claimant FROM tasks WHERE episode=? AND id=?', (row['episode'], tid)).fetchone()
            args = (row['episode'], tid)
            if action == 'accept':
                if state['state'] == 'accepted' and state['claimant'] == row['recipient']:
                    return
                if state['state'] != 'pending':
                    raise Conflict('Task is no longer available')
                db.execute("UPDATE tasks SET state='accepted',claimant=? WHERE episode=? AND id=?", (row['recipient'], *args))
                db.execute('DELETE FROM declines WHERE episode=? AND task=? AND recipient=?', (*args, row['recipient']))
            elif action == 'decline':
                if state['state'] != 'pending':
                    raise Conflict('Task is no longer available')
                db.execute('INSERT OR IGNORE INTO declines VALUES (?,?,?)', (*args, row['recipient']))
            else:
                if state['claimant'] != row['recipient']:
                    raise Denied('Unavailable')
                if state['state'] not in ('accepted', 'completed'):
                    raise Conflict('Task cannot be completed')
                db.execute("UPDATE tasks SET state='completed' WHERE episode=? AND id=?", args)

    def close(self, owner_token, eid, state, recovery_message=None, recovery_recipients=None):
        if state not in ('recovered', 'cancelled'):
            raise Invalid('Invalid closing state')
        if state == 'recovered':
            text(recovery_message, 10000)
            if recovery_recipients is not None:
                if not isinstance(recovery_recipients, list) or len(recovery_recipients) > 100:
                    raise Invalid('Choose unique recovery recipients')
                for recipient in recovery_recipients:
                    text(recipient, 80, identifier=True)
                if len(set(recovery_recipients)) != len(recovery_recipients):
                    raise Invalid('Choose unique recovery recipients')
        elif recovery_recipients not in (None, []):
            raise Invalid('Cancellation cannot select recovery recipients')
        with self.transaction() as db:
            row = self._episode(db, owner_token, eid)
            if row['state'] == state:
                return
            if row['state'] != 'active':
                raise Conflict('Episode is already closed')
            if db.execute("SELECT 1 FROM jobs WHERE episode=? AND status IN ('sending','uncertain')", (eid,)).fetchone():
                raise Conflict('Resolve in-flight or uncertain sends before closing')
            if state == 'recovered':
                value = self.open(eid, row['data'])
                informed = {x[0] for x in db.execute("SELECT recipient FROM jobs WHERE episode=? AND kind='illness' AND status='accepted'", (eid,))}
                selected = informed if recovery_recipients is None else set(recovery_recipients)
                if recovery_recipients is not None and not selected <= informed:
                    raise Conflict('Recovery recipients must have an accepted initial notification')
                for recipient in value['recipients']:
                    if recipient['id'] in selected:
                        self._job(db, eid, {**recipient, 'message': recovery_message}, 'recovery', int(self.clock()))
            db.execute("UPDATE jobs SET status='cancelled' WHERE episode=? AND kind IN ('illness','update') AND status='queued'", (eid,))
            db.execute("UPDATE tasks SET state='closed' WHERE episode=? AND state!='completed'", (eid,))
            closure_identity = 'closure:' + eid
            closure_record = {'version': 1, 'closed_at': max(int(self.clock()), row['created'])}
            db.execute('INSERT INTO metadata VALUES (?,?)',
                       (closure_identity, self.seal(closure_identity, closure_record)))
            db.execute('UPDATE episodes SET state=? WHERE id=?', (state, eid))

    def quarantine_expired(self):
        with self.transaction() as db:
            db.execute("UPDATE jobs SET status='uncertain' WHERE status='sending' AND lease<=?", (int(self.clock()),))

    def dispatch_one(self, sender, *, channels=None):
        # Held across the provider call, but never a long-running SQL transaction.
        # A lease expiry alone cannot make a still-running sender safe to reconcile.
        with delivery_lock(self.path, timeout=10):
            return self._dispatch_one(sender, channels=channels)

    def _dispatch_one(self, sender, *, channels=None):
        """Call a trusted configured adapter once. Acceptance is not delivery.

        An adapter returns a nonempty receipt only on positive provider acceptance.
        Unclassified failures are ambiguous and never automatically replayed.
        """
        if not callable(sender):
            raise Invalid('No sender configured')
        if channels is not None and (not isinstance(channels, (tuple, list)) or not channels or
                                     any(channel not in ('email', 'sms', 'whatsapp', 'push') for channel in channels)):
            raise Invalid('Invalid sender channel scope')
        now = int(self.clock())
        with self.transaction() as db:
            db.execute("UPDATE jobs SET status='uncertain' WHERE status='sending' AND lease<=?", (now,))
            db.execute("UPDATE jobs SET status='failed' WHERE status='queued' AND kind='illness' AND EXISTS "
                       '(SELECT 1 FROM recipients r WHERE r.episode=jobs.episode AND r.recipient=jobs.recipient AND r.expires<=?)', (now,))
            row, payload = None, None
            for candidate in db.execute("SELECT * FROM jobs WHERE status='queued' AND due<=? ORDER BY rowid", (now,)):
                item = self.open(candidate['id'], candidate['payload'])
                if channels is None or item['channel'] in channels:
                    row, payload = candidate, item
                    break
            if row is None:
                return False
            attempts = row['attempts'] + 1
            db.execute("UPDATE jobs SET status='sending',attempts=?,lease=? WHERE id=?", (attempts, now + 300, row['id']))
        receipt, outcome = None, 'accepted'
        try:
            receipt = sender(payload)
            if not isinstance(receipt, str) or not 1 <= len(receipt) <= 1000:
                outcome = 'uncertain'
        except SendFailure as error:
            outcome = error.outcome
        except Exception:
            outcome = 'uncertain'
        if outcome == 'retryable':
            outcome = 'queued' if attempts < 5 else 'failed'
        elif outcome == 'permanent':
            outcome = 'failed'
        with self.transaction() as db:
            db.execute('UPDATE jobs SET status=?,due=?,receipt=?,lease=NULL WHERE id=? AND attempts=? AND status IN (\'sending\',\'uncertain\')',
                       (outcome, int(self.clock()) + min(3600, 30 * 2 ** (attempts - 1)),
                        self.seal(row['id'] + ':receipt', receipt) if outcome == 'accepted' else None, row['id'], attempts))
        return True

    def review_job(self, job_id):
        """Trusted operator only: no message, destination, capability or receipt."""
        text(job_id, 80, identifier=True)
        with self.transaction() as db:
            row = db.execute('SELECT j.id,j.episode,j.kind,j.status,j.attempts,j.due,j.lease,e.state AS episode_state '
                             'FROM jobs j JOIN episodes e ON e.id=j.episode WHERE j.id=?', (job_id,)).fetchone()
            if row is None:
                raise Denied('Unavailable')
            entries = db.execute('SELECT name,value FROM metadata WHERE name LIKE ? ORDER BY name',
                                 ('resolution:' + job_id + ':%',)).fetchall()
            return {**dict(row), 'resolutions': [
                {key: value for key, value in self.open(entry['name'], entry['value']).items()
                 if key in ('attempt', 'outcome', 'retry', 'result', 'recorded_at')}
                for entry in entries]}

    def reconcile_job(self, decision, *, apply=False):
        """Trusted operator assertion of externally verified evidence, never a lookup.

        No HTTP route. Dry-run by default. A decision can only settle one uncertain
        attempt; identical replay is safe, changed evidence/decisions conflict.
        """
        fields = {'job_id', 'attempt', 'outcome', 'retry', 'operator', 'evidence_source', 'evidence_reference'}
        if not isinstance(decision, dict) or set(decision) != fields or type(apply) is not bool:
            raise Invalid('Invalid reconciliation fields')
        job_id = text(decision['job_id'], 80, identifier=True)
        attempt = decision['attempt']
        if type(attempt) is not int or not 1 <= attempt <= 5:
            raise Invalid('An exact attempt number is required')
        if decision['outcome'] not in ('accepted', 'not_accepted') or type(decision['retry']) is not bool:
            raise Invalid('Explicit evidence outcome and retry choice required')
        if decision['retry'] and decision['outcome'] != 'not_accepted':
            raise Invalid('Never retry an accepted or unresolved send')
        if decision['evidence_source'] not in ('provider_record', 'provider_support'):
            raise Invalid('Authoritative provider evidence is required')
        for name, maximum in (('operator', 200), ('evidence_reference', 1000)):
            text(decision[name], maximum)
            if any(ord(c) < 32 or ord(c) == 127 for c in decision[name]):
                raise Invalid('Use a single-line private evidence reference')
        decision = json.loads(encoded(decision))
        identity = f'resolution:{job_id}:{attempt}'
        now = int(self.clock())
        with delivery_lock(self.path), self.transaction() as db:
            existing = db.execute('SELECT value FROM metadata WHERE name=?', (identity,)).fetchone()
            if existing is not None:
                record = self.open(identity, existing['value'])
                if record['decision'] != decision:
                    raise Conflict('This attempt already has a different resolution')
                return {'job_id': job_id, 'attempt': attempt, 'result': record['result'], 'applied': True, 'replayed': True}
            row = db.execute('SELECT j.*,e.state AS episode_state FROM jobs j JOIN episodes e ON e.id=j.episode '
                             'WHERE j.id=?', (job_id,)).fetchone()
            if row is None:
                raise Denied('Unavailable')
            if row['attempts'] != attempt or row['status'] not in ('uncertain', 'sending'):
                raise Conflict('Job state or attempt changed; review again')
            if row['status'] == 'sending' and (row['lease'] is None or row['lease'] > now):
                raise Conflict('Sending lease has not expired')
            result = 'accepted' if decision['outcome'] == 'accepted' else 'failed'
            if decision['retry']:
                if attempt >= 5:
                    raise Conflict('Retry limit reached')
                if row['kind'] == 'illness':
                    recipient = db.execute('SELECT expires FROM recipients WHERE episode=? AND recipient=?',
                                           (row['episode'], row['recipient'])).fetchone()
                    if row['episode_state'] != 'active' or recipient is None or recipient['expires'] <= now:
                        raise Conflict('Cannot retry a closed episode or expired personal link')
                elif row['kind'] == 'update' and row['episode_state'] != 'active':
                    raise Conflict('Cannot retry an update after episode closure')
                elif row['kind'] == 'recovery' and row['episode_state'] != 'recovered':
                    raise Conflict('Recovery episode state changed')
                result = 'queued'
            answer = {'job_id': job_id, 'attempt': attempt, 'result': result, 'applied': apply, 'replayed': False}
            if not apply:
                return answer
            record = {'decision': decision, 'attempt': attempt, 'outcome': decision['outcome'],
                      'retry': decision['retry'], 'result': result, 'recorded_at': now}
            db.execute('INSERT INTO metadata(name,value) VALUES (?,?)', (identity, self.seal(identity, record)))
            receipt = self.seal(job_id + ':receipt', 'operator-reconciled:' + identity) if result == 'accepted' else None
            db.execute('UPDATE jobs SET status=?,due=?,lease=NULL,receipt=? WHERE id=?',
                       (result, now + 30, receipt, job_id))
            return answer
