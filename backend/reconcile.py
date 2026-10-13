"""Private operator review of uncertain sends. No provider calls; dry-run by default."""
import argparse
import json
import os
import sys
from pathlib import Path

from backend.dispatch_lock import DeliveryBusy
from backend.service import Conflict, Denied, Invalid, Store


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Invalid('Duplicate decision field')
        result[key] = value
    return result


def load_decision(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 16384:
        raise Invalid('Use a bounded private decision file')
    with path.open(encoding='utf-8') as stream:
        return json.load(stream, object_pairs_hook=unique_fields)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--job', help='Inspect one job without exposing content or evidence references')
    action.add_argument('--decision', type=Path, help='Private JSON containing verified evidence and an explicit decision')
    parser.add_argument('--apply', action='store_true', help='Persist the verified decision; requires --decision')
    args = parser.parse_args(argv)
    if args.apply and not args.decision:
        parser.error('--apply requires --decision')
    try:
        if not args.database.is_file() or args.database.is_symlink():
            raise Invalid('Existing dedicated database required')
        key = bytes.fromhex(os.environ.pop('AUTOFEVER_STORE_KEY_HEX', ''))
        store = Store(args.database, key)
        result = store.review_job(args.job) if args.job else store.reconcile_job(load_decision(args.decision), apply=args.apply)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (DeliveryBusy, Conflict):
        print('No new decision applied: active delivery or changed job/decision. Stop workers and review again.', file=sys.stderr)
        return 3
    except (Invalid, Denied, ValueError, OSError):
        print('Review refused. Check private configuration, exact job/attempt and provider evidence. No send attempted.', file=sys.stderr)
        return 2
    except Exception:
        print('Review failed. Inspect persisted state before retrying the identical decision. No send attempted.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
