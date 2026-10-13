"""Opt-in cleanup of closed Autofever history after the owner's chosen period."""

import argparse
import sys
from pathlib import Path

from backend.hosted import read_secret
from backend.service import Conflict, Invalid, Store


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--key-file', type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', action='store_true', help='Validate the dedicated store and key only; delete nothing')
    action.add_argument('--purge', action='store_true', help='Delete opted-in expired closed history in a bounded batch')
    parser.add_argument('--limit', type=int, default=100, help='Maximum episodes to remove per run, 1 to 1000 (default 100)')
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 1000:
        parser.error('Choose a retention batch between 1 and 1000')
    try:
        if (not args.database.is_file() or args.database.is_symlink() or
                args.database.stat().st_size <= 0):
            raise Invalid('Existing dedicated Autofever database required')
        store = Store(args.database, bytes.fromhex(read_secret(args.key_file)))
        if args.check:
            print('Retention configuration valid. No records deleted; provider and backup state not checked.')
            return 0
        deleted = store.purge_expired_history(limit=args.limit)
        print(f'Removed {deleted} expired closed episode(s) from the live store. Backups and recipient copies are unchanged.')
        return 0
    except Conflict:
        print('Retention skipped: delivery or reconciliation is active. Retry on the next scheduled run.', file=sys.stderr)
        return 3
    except Exception:
        print('Retention configuration or store validation failed. No deletion was confirmed.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
