"""Opt-in SMTP queue worker. Configuration checks never connect to a provider."""
import argparse
import json
import os
import re
import signal
import stat
import sys
import threading
from pathlib import Path

from backend.service import Invalid, Store
from backend.dispatch_lock import DeliveryBusy
from backend.smtp import SMTPConfig, SMTPSender


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Invalid('Duplicate SMTP configuration field')
        result[key] = value
    return result


def _read_private_file(path, *, maximum):
    """Read a bounded private regular file without following symlinks."""
    path = Path(path)
    descriptor = None
    try:
        if path.is_symlink():
            raise Invalid('Use private regular credential files')
        flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
        descriptor = os.open(path, flags)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise Invalid('Use bounded private regular files')
        if os.name == 'posix' and stat.S_IMODE(info.st_mode) & 0o077:
            raise Invalid('Credential files must not be readable by group or others')
        with os.fdopen(descriptor, 'rb') as stream:
            descriptor = None
            data = stream.read(maximum + 1)
    except Invalid:
        raise
    except (OSError, TypeError, ValueError):
        raise Invalid('Use bounded private regular files') from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(data) > maximum:
        raise Invalid('Use bounded private regular files')
    return data


def load_config(path):
    raw = _read_private_file(path, maximum=256 * 1024)
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_fields)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise Invalid('Use a valid private SMTP configuration file') from None
    return SMTPConfig.from_dict(value)


def _store_key_from_file(path):
    try:
        value = _read_private_file(path, maximum=128).decode('ascii').strip()
    except UnicodeDecodeError:
        raise Invalid('Use a valid private store-key file') from None
    if not re.fullmatch(r'[0-9a-f]{64}', value):
        raise Invalid('Use a valid private store-key file')
    return bytes.fromhex(value)


def _smtp_password_from_file(path):
    try:
        value = _read_private_file(path, maximum=4096).decode('ascii')
    except UnicodeDecodeError:
        raise Invalid('Use a valid private SMTP password file') from None
    if value.endswith('\n'):
        value = value[:-1]
        if value.endswith('\r'):
            value = value[:-1]
    return value


def run_worker(store, sender, *, max_jobs=1, stop=None, poll_seconds=5):
    if max_jobs is not None and (type(max_jobs) is not int or not 1 <= max_jobs <= 100):
        raise Invalid('Choose 1 to 100 attempts or explicit continuous mode')
    if type(poll_seconds) is not int or not 1 <= poll_seconds <= 60:
        raise Invalid('Choose a polling interval of 1 to 60 seconds')
    if not isinstance(sender, SMTPSender):
        raise Invalid('Configured SMTP sender required')
    stop = stop or threading.Event()
    attempted = 0
    while not stop.is_set() and (max_jobs is None or attempted < max_jobs):
        if sender.halted:
            raise Invalid('SMTP account or TLS configuration requires operator attention')
        try:
            dispatched = store.dispatch_one(sender, channels=sender.channels)
        except DeliveryBusy:
            # Another process still owns dispatch; no job was claimed by us.
            dispatched = False
        if dispatched:
            attempted += 1
            if sender.halted:
                raise Invalid('SMTP account or TLS configuration requires operator attention')
            if sender.retry_after:
                if max_jobs is not None:
                    break
                stop.wait(sender.retry_after)
        elif max_jobs is not None:
            break
        else:
            stop.wait(poll_seconds)
    return attempted


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--smtp-config', type=Path, required=True)
    parser.add_argument('--store-key-file', type=Path,
                        help='Read the 32-byte store key from a private file (systemd credential compatible)')
    parser.add_argument('--smtp-password-file', type=Path,
                        help='Read the SMTP password from a private file (systemd credential compatible)')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', action='store_true', help='Validate local settings only; no network and no queue consumption')
    action.add_argument('--send', action='store_true', help='Explicitly authorize this process to dispatch approved queued emails')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--max-jobs', type=int, default=1, help='Maximum queue attempts in a bounded run, 1 to 100 (default 1)')
    mode.add_argument('--continuous', action='store_true', help='Run until stopped; respect queue retry delays')
    parser.add_argument('--poll-seconds', type=int, default=5)
    args = parser.parse_args(argv)
    if (args.store_key_file is None) != (args.smtp_password_file is None):
        parser.error('Use both credential files together or use both existing environment variables')
    if not 1 <= args.max_jobs <= 100 or not 1 <= args.poll_seconds <= 60:
        parser.error('Invalid bounded attempt limit or polling interval')
    try:
        if not args.database.is_file() or args.database.is_symlink():
            raise Invalid('Existing dedicated Autofever database required')
        config = load_config(args.smtp_config)
        password_from_environment = os.environ.pop('AUTOFEVER_SMTP_PASSWORD', None)
        key_from_environment = os.environ.pop('AUTOFEVER_STORE_KEY_HEX', None)
        if args.store_key_file is not None:
            if password_from_environment is not None or key_from_environment is not None:
                raise Invalid('Choose either private credential files or environment credentials')
            password = _smtp_password_from_file(args.smtp_password_file)
            key = _store_key_from_file(args.store_key_file)
        else:
            password = password_from_environment or ''
            key = bytes.fromhex(key_from_environment or '')
        sender = SMTPSender(config, password)
        store = Store(args.database, key)
    except Exception:
        print('Local configuration validation failed. Check the private config, environment and dedicated store. No send attempted.', file=sys.stderr)
        return 2
    if args.check:
        print('Local configuration valid. No network used, no queue consumed; SMTP credentials and public help URL are not verified.')
        return 0
    stop = threading.Event()
    previous = {}
    try:
        for name in (signal.SIGINT, signal.SIGTERM):
            previous[name] = signal.signal(name, lambda *_: stop.set())
        attempted = run_worker(store, sender, max_jobs=None if args.continuous else args.max_jobs,
                               stop=stop, poll_seconds=args.poll_seconds)
        print(f'Processed {attempted} queue attempt(s). Inspect persisted outcomes; this is not delivery confirmation.')
        return 0
    except Invalid:
        print('Worker stopped: SMTP account or configuration needs attention. Inspect persisted outcomes before resuming.', file=sys.stderr)
        return 3
    except Exception:
        print('Worker stopped after an internal error. Inspect persisted outcomes before resuming; no automatic replay of uncertain sends.', file=sys.stderr)
        return 1
    finally:
        for name, handler in previous.items():
            signal.signal(name, handler)


if __name__ == '__main__':
    raise SystemExit(main())
