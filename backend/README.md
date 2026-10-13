# Autofever service core

This is the first persistent backend component for the real notification/help/recovery chain. It is **an internal Python library, not a deployed API or a connected notification provider**. The mobile preview still uses its own browser storage. Do not expose this library directly to the internet or describe passing unit tests as message-delivery evidence.

## Run the tests

Python 3.11 or newer is required. From the repository root, create an isolated environment:

```powershell
python -m venv backend/.venv
./backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
./backend/.venv/Scripts/python.exe -m unittest discover -s backend/tests -v
```

On Linux, the environment's Python executable is `backend/.venv/bin/python`. The direct cryptography dependency is pinned; this is not yet a complete cross-platform deployment lockfile. Tests create disposable SQLite files and synthetic recipients under `.invalid`, generate only test capabilities, and inject in-process sender functions. They make no network requests and never read the mobile preview's browser database.

## Implemented boundary

`backend.service.Store` is the authoritative in-process interface. There is no HTTP contract yet. The types and allowed values below match the service's strict validation and the test fixtures; the eventual HTTP contract must be reviewed before connecting the browser.

| Operation | Inputs | Result and rules |
| --- | --- | --- |
| `Store(path, key, clock=...)` | Dedicated SQLite file; operator-managed 32-byte key; optional test clock | Initializes a new empty Autofever store or validates an existing one. Rejects another application's database, missing schema, wrong key and missing key check. |
| `create_owner()` | Trusted operator call only | Returns a random owner capability once; only its SHA-256 hash is stored. This is not public signup or a decision to require an app account. |
| `activate(owner, command, snapshot, link_ttl=...)` | Valid owner capability; stable idempotency key; saved snapshot; explicit lifetime of 60–604800 seconds | Atomically snapshots one episode, recipient capabilities, tasks and outgoing jobs. Same command/content returns the same episode. Changed content with the same command fails. |
| `episode(owner, episode_id)` | Owner capability | Own episode state and per-recipient notification status/attempts; no recipient capability or destination is exposed. |
| `recipient(token)` | A recipient capability | That recipient's message and assigned tasks only. Reading does not acknowledge or claim anything. |
| `acknowledge(token)` | A valid recipient capability | Explicit, repeatable receipt acknowledgment, separate from provider acceptance. |
| `respond(token, task_id, action)` | `accept`, `decline` or `complete` | Only assigned helpers may act. One helper claims a task; only that helper can complete it. Another helper cannot see the claimant's identity. |
| `close(owner, episode_id, state, recovery_message=None)` | `recovered` or `cancelled`; message required for recovery | Stops queued initial notices and outstanding tasks; invalidates action capabilities through episode state. Recovery queues one notice for each recipient whose initial notice was positively accepted by a provider. Cancellation queues none. |
| `dispatch_one(sender)` | Trusted callable provider adapter | Claims and persists one due job, then calls the adapter outside the transaction. No configured sender means no queue consumption. |
| `quarantine_expired()` | Trusted worker/maintenance call | Marks expired in-flight jobs uncertain; never assumes a crashed worker did not send. |

Snapshot shape (synthetic example):

```json
{
  "recipients": [
    {"id": "helper-1", "channel": "email", "destination": "helper@example.invalid", "message": "I am unavailable today. Could you help?"}
  ],
  "tasks": [
    {"id": "food", "title": "Bring soup", "timing": "This evening", "assignees": ["helper-1"]}
  ]
}
```

Limits are 100 recipients, 100 tasks, 80-character identifiers and 10,000-character messages. Unknown fields are rejected rather than silently losing intended behavior. Channels accepted as data are `email`, `sms`, `whatsapp` and `push`; none has a real adapter yet. Phone destinations require international `+` notation. Recurrence, backup-helper and reminder settings from the browser are **not yet represented**: do not discard them when constructing a server snapshot. Expand and test the contract first. One recipient currently has one chosen channel; multi-channel preference/fallback remains work.

## Delivery semantics

The worker persists `sending` before invoking a sender. The adapter receives an envelope containing the unique job ID/idempotency key, destination, message and (for initial illness notices) recipient action token. The adapter is a trusted component; do not log the envelope. It must return a nonempty provider receipt only after positive acceptance. `accepted` is **not** delivery, reading or formal acceptance of an absence.

- `SendFailure('retryable')`: only for a definite non-acceptance; retry with bounded delay, at most five attempts.
- `SendFailure('permanent')`: definite rejection, no retry.
- `SendFailure('uncertain')`, timeout, unknown exception or invalid receipt: quarantine as `uncertain`, no automatic replay.
- A process crash leaves a five-minute lease. An expired lease becomes uncertain rather than being blindly resent. Lease duration is an internal initial value, not a promised service deadline.
- Queued initial messages whose recipient token expired are failed without sending a dead link.
- SQLite transactions prevent duplicate claims by concurrent workers. This **does not promise exactly-once delivery at an external provider**.

Closing is currently refused while any send is in flight or uncertain. Starting another episode is refused while previous notifications are queued, in flight or uncertain, to avoid racing a new illness notice against an old recovery notice. No operator/provider reconciliation interface exists yet. These are explicit backend integration blockers to solve before online use, not a complete UX for uncertain delivery. Do not manually rewrite database statuses to bypass them.

## Storage and access boundaries

Episode content and sender envelopes/receipts are AES-256-GCM encrypted with independent random 12-byte nonces and authenticated record identity. HKDF derives separate encryption and digest keys from the supplied operator key. A blob copied to another record cannot be decrypted as that record. Keys are never generated into this database or included in Git. The application process can decrypt content; this is encryption at rest, **not end-to-end encryption** or protection against a compromised server.

IDs, relationship metadata, timestamps, task state, attempts and delivery states remain visible in SQLite. Raw owner capabilities are not stored; recipient capabilities are hashed for lookup, and raw recipient tokens exist only in encrypted delivery envelopes. Anyone possessing a valid capability can exercise its scoped rights. Sharing, theft, expiry, revocation, safe browser storage and device recovery must be addressed by the transport/provisioning design.

Use a private operator-owned directory, a dedicated key from outside the repository, restricted filesystem permissions and separately protected key backups. Initial POSIX database creation requests mode `0600`; Windows ACLs and parent-directory permissions require operator verification. The service does not harden preexisting file permissions or provide a key-rotation/retention/deletion system. It cannot recover data without the key. Do not point it at Hire.ai's database, secrets or volumes.

Implementation references: [Python SQLite transaction documentation](https://docs.python.org/3/library/sqlite3.html), [cryptography authenticated encryption](https://cryptography.io/en/latest/hazmat/primitives/aead/). These document primitives, not a security certification of Autofever.

## Verification checkpoint — 13 October 2026

24 automated cases pass locally on Python 3.11.15 and cryptography 46.0.7. Coverage includes persistent idempotency, owner/recipient isolation, concurrent activation and job claims, exclusive task claims, private declines, acknowledgments, recovery targeting, cancellation, retries, ambiguous outcomes, worker crash leases, ciphertext substitution, wrong keys, transaction rollback and refusal to modify another application's database. Additional cases first exposed missing database-identity checks and missing recovery-order protection; they pass after the fixes.

Remaining required work: HTTP authentication/provisioning and rate limits; browser integration without losing saved profile fields; real provider adapters and delivery evidence; recipient web pages; updates, reminders, recurrence, escalation, backup helpers and fallback channels; handling/reconciling uncertain jobs; deletion/retention, database backup/restore and key rotation; production dependency/security review; Linux and shared-host testing; HTTPS deployment on the existing `013-hire-ai` host as `028-autofever`. No new server, paid service, production data, real message or server configuration was used by this work.
