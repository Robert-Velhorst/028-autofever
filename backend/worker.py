"""Opt-in SMTP queue worker. Configuration checks never connect to a provider."""
import argparse
import json
import os
import signal
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


def load_config(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 256 * 1024:
        raise Invalid('Use a bounded, private SMTP configuration file')
    with path.open(encoding='utf-8') as stream:
        return SMTPConfig.from_dict(json.load(stream, object_pairs_hook=unique_fields))


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
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', action='store_true', help='Validate local settings only; no network and no queue consumption')
    action.add_argument('--send', action='store_true', help='Explicitly authorize this process to dispatch approved queued emails')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--max-jobs', type=int, default=1, help='Maximum queue attempts in a bounded run, 1 to 100 (default 1)')
    mode.add_argument('--continuous', action='store_true', help='Run until stopped; respect queue retry delays')
    parser.add_argument('--poll-seconds', type=int, default=5)
    args = parser.parse_args(argv)
    if not 1 <= args.max_jobs <= 100 or not 1 <= args.poll_seconds <= 60:
        parser.error('Invalid bounded attempt limit or polling interval')
    try:
        if not args.database.is_file() or args.database.is_symlink():
            raise Invalid('Existing dedicated Autofever database required')
        config = load_config(args.smtp_config)
        sender = SMTPSender(config, os.environ.pop('AUTOFEVER_SMTP_PASSWORD', ''))
        key = bytes.fromhex(os.environ.pop('AUTOFEVER_STORE_KEY_HEX', ''))
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
