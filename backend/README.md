# Autofever service core

This is the persistent backend component for the notification/help/recovery chain, with **local-only owner and recipient web interfaces**. A concrete [SMTP email adapter and opt-in worker](smtp.md) are implemented and locally tested, but no real provider is configured and the application is not deployed. The standalone preview still uses only browser storage; the opt-in `/owner` mode connects that same profile editor to the service. Do not expose the development listener to the internet or describe passing tests as external message-delivery evidence.

## Run the tests

Python 3.11 or newer is required. From the repository root, create an isolated environment:

```powershell
python -m venv backend/.venv
./backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
./backend/.venv/Scripts/python.exe -m unittest discover -s backend/tests -v
```

On Linux, the environment's Python executable is `backend/.venv/bin/python`. The direct cryptography dependency is pinned; this is not yet a complete cross-platform deployment lockfile. Tests create disposable SQLite files and synthetic recipients under `.invalid`, generate only test capabilities, and use injected sender functions or temporary loopback TLS SMTP servers. The HTTP integration test also uses an ephemeral loopback listener. No tests contact external providers or read the mobile preview's browser database.

## Implemented boundary

`backend.service.Store` is the authoritative in-process interface. HTTP routes are documented in [OpenAPI](openapi.yaml), with the optional owner flow explained in [the owner contract](owner-api.md). Owner provisioning and dispatch remain trusted in-process operations with no HTTP routes.

| Operation | Inputs | Result and rules |
| --- | --- | --- |
| `Store(path, key, clock=...)` | Dedicated SQLite file; operator-managed 32-byte key; optional test clock | Initializes a new empty Autofever store or validates an existing one. Rejects another application's database, missing schema, wrong key and missing key check. |
| `create_owner()` | Trusted operator call only | Returns a random owner capability once; only its SHA-256 hash is stored. This is not public signup or a decision to require an app account. |
| `activate(owner, command, snapshot, link_ttl=...)` | Valid owner capability; stable idempotency key; saved snapshot; explicit lifetime of 60–604800 seconds | Atomically snapshots one episode, recipient capabilities, tasks and outgoing jobs. Same command/content returns the same episode. Changed content with the same command fails. |
| `episode(owner, episode_id)` | Owner capability | Own immutable snapshot (including own selected contacts/destinations), notification states/attempts, acknowledgments, claims and declines; never recipient capabilities. |
| `latest_episode(owner)` | Owner capability | Most recently created own episode including a terminal episode, or `None`; no other owner's records. |
| `activate_profile(owner, command, profile, contacts, link_ttl=...)` | Saved profile plus exactly its selected contacts | Validates/converts the preview format, then uses the same atomic, idempotent activation path. Stores an immutable, encrypted copy of all supplied preparation fields. |
| `recipient(token)` | A recipient capability | That recipient's message and assigned tasks only. Reading does not acknowledge or claim anything. |
| `acknowledge(token)` | A valid recipient capability | Explicit, repeatable receipt acknowledgment, separate from provider acceptance. |
| `respond(token, task_id, action)` | `accept`, `decline` or `complete` | Only assigned helpers may act. One helper claims a task; only that helper can complete it. Another helper cannot see the claimant's identity. |
| `close(owner, episode_id, state, recovery_message=None)` | `recovered` or `cancelled`; message required for recovery | Stops queued initial notices and outstanding tasks; invalidates action capabilities through episode state. Recovery queues one notice for each recipient whose initial notice was positively accepted by a provider. Cancellation queues none. |
| `dispatch_one(sender, channels=None)` | Trusted callable provider adapter; optional nonempty channel list/tuple | Claims and persists one due job in the selected channels, then calls the adapter outside the transaction. No configured sender means no queue consumption. SMTP selects only email jobs; queue expiry/lease maintenance still applies across channels. |
| `quarantine_expired()` | Trusted worker/maintenance call | Marks expired in-flight jobs uncertain; never assumes a crashed worker did not send. |
| `review_job(job_id)` | Trusted operator call; exact job ID | Redacted job state and resolution summaries; no addresses, messages, capabilities or evidence text. |
| `reconcile_job(decision, apply=False)` | Trusted operator; exact attempt and verified provider evidence | Previews by default; explicit application atomically records an encrypted decision and settles uncertainty. Optional retry requires proven non-acceptance, a valid lifecycle/link and remaining attempts. No provider lookup or HTTP route. |

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

Limits are 100 recipients, 100 tasks, 80-character identifiers and 10,000-character core messages (2,000 for preview-profile messages). Unknown fields are rejected rather than silently losing intended behavior. Channels accepted by the core as data are `email`, `sms`, `whatsapp` and `push`. Email has an implemented SMTP adapter; the other channels have no concrete adapters yet, and none is configured for live delivery. Phone destinations require international `+` notation. Preview activation preserves recurrence, backup-helper, check-in, duration and recovery preferences in encrypted `preparation`, but **does not execute recurring jobs, check-ins or automatic backup/fallback**. The owner UI labels these preferences accordingly. One recipient currently has one chosen initial channel. Profiles with multiple selected channels or Push fail before activation rather than silently choosing a destination or discarding channels. Multichannel/fallback and Push remain required work, not removed product requirements.

## Delivery semantics

The worker persists `sending` before invoking a sender. The adapter receives an envelope containing the unique job ID/idempotency key, destination, message and (for initial illness notices) recipient action token. The adapter is a trusted component; do not log the envelope. It must return a nonempty acceptance reference only after positive server/provider acceptance. SMTP returns a local Message-ID-based reference, not a provider-issued delivery receipt. `accepted` is **not** delivery, reading or formal acceptance of an absence.

- `SendFailure('retryable')`: only for a definite non-acceptance; retry with bounded delay, at most five attempts.
- `SendFailure('permanent')`: definite rejection, no retry.
- `SendFailure('uncertain')`, timeout, unknown exception or invalid receipt: quarantine as `uncertain`, no automatic replay.
- A process crash leaves a five-minute lease. An expired lease becomes uncertain rather than being blindly resent. Lease duration is an internal initial value, not a promised service deadline.
- Queued initial messages whose recipient token expired are failed without sending a dead link.
- SQLite transactions prevent duplicate claims by concurrent workers. This **does not promise exactly-once delivery at an external provider**.

Closing is currently refused while any send is in flight or uncertain. Starting another episode is refused while previous notifications are queued, in flight or uncertain, to avoid racing a new illness notice against an old recovery notice. The [private reconciliation CLI](reconciliation.md) can settle an exact uncertain attempt when an operator has verified authoritative provider evidence. It does not retrieve or independently validate that evidence; unresolvable outcomes remain uncertain. A complete nontechnical uncertainty experience and provider-specific lookup remain production work. Do not manually rewrite database statuses to bypass these guards.

Dispatch and reconciliation now share an OS-level lock beside the dedicated database. It remains held during the provider call without holding a long SQLite transaction; reconciliation cannot race a live sender even when its lease expires. This initial design serializes dispatch per store. All processes must use this version and the same canonical path on local storage; stop older workers before upgrading, and never remove a lock file to bypass ownership. The sidecar contains no secret. See the reconciliation guide for platform and filesystem limits.

## Storage and access boundaries

Episode content and sender envelopes/receipts are AES-256-GCM encrypted with independent random 12-byte nonces and authenticated record identity. HKDF derives separate encryption and digest keys from the supplied operator key. A blob copied to another record cannot be decrypted as that record. Keys are never generated into this database or included in Git. The application process can decrypt content; this is encryption at rest, **not end-to-end encryption** or protection against a compromised server.

IDs, relationship metadata, timestamps, task state, attempts and delivery states remain visible in SQLite. Raw owner capabilities are not stored; recipient capabilities are hashed for lookup, and raw recipient tokens exist only in encrypted delivery envelopes. Anyone possessing a valid capability can exercise its scoped rights. Sharing, theft, expiry, revocation, safe browser storage and device recovery must be addressed by the transport/provisioning design.

Use a private operator-owned directory, a dedicated key from outside the repository, restricted filesystem permissions and separately protected key backups. Initial POSIX database creation requests mode `0600`; Windows ACLs and parent-directory permissions require operator verification. The service does not harden preexisting file permissions or provide a key-rotation/retention/deletion system. It cannot recover data without the key. Do not point it at Hire.ai's database, secrets or volumes.

Implementation references: [Python SQLite transaction documentation](https://docs.python.org/3/library/sqlite3.html), [cryptography authenticated encryption](https://cryptography.io/en/latest/hazmat/primitives/aead/). These document primitives, not a security certification of Autofever.

## Verification checkpoint — 13 October 2026

86 automated cases pass locally on Python 3.11.15 and cryptography 46.0.7: 24 service cases, 12 recipient WSGI boundary cases, eight owner/profile cases, one real loopback HTTP integration case, ten SMTP unit cases, 15 SMTP TLS/worker integration cases and 16 reconciliation/process-lock cases. The suite also passes with resource warnings treated as errors. Coverage includes persistent idempotency, owner/recipient isolation, concurrent activation and job claims, exclusive task claims, private declines, acknowledgments, recovery targeting, cancellation, retries, ambiguous outcomes, worker crash leases, ciphertext substitution, wrong keys, transaction rollback and refusal to modify another application's database. HTTP cases exercise origin/host restrictions, bearer scope, duplicate JSON fields, malformed bodies, size limits, method/path restrictions, generic errors and persistence across reopening the store. Owner cases additionally cover lossless preparation, helper outcomes, strict unsupported-channel rejection, repeatable closure and mismatched prepared snapshots. SMTP cases cover verified TLS before authentication, private single-recipient MIME messages, explicit rejection versus lost replies, persistent uncertainty, account-failure suspension, cooldown, channel isolation, graceful stop, non-sending configuration checks and actual CLI send outcomes against a local test server. Reconciliation cases include encrypted/idempotent decisions, bounded explicit retry, unchanged dry-runs, rollback, active-sender exclusion, separate-process contention and actual subprocess death. See [SMTP verification and limits](smtp.md#verification) and [reconciliation boundaries](reconciliation.md).

A separate local Chromium browser check exercised the actual HTTP service with disposable synthetic records, without mocked fetch: personal link, explicit acknowledgment, accept/decline/complete, second-helper conflict, offline error/reload recovery and missing/invalid-link states. Page identity, meaningful content, absence of framework overlays, clean successful-flow console, same-origin requests, stripped URL fragments, empty browser storage and screenshots were checked at 320, 390 and 1280 CSS-pixel widths. Deliberately induced offline/404/409 responses are expected errors, not successful operations. This is not physical-phone, Safari, screen-reader or production evidence.

## Recipient web interface

The Dutch page at `/help#RECIPIENT_CAPABILITY` shows only that recipient's message and assigned tasks. No account, app installation or owner capability is needed. Opening the page or fetching data does **not** acknowledge the message. The reader explicitly chooses **Ik heb dit gelezen**, **Ik pak dit op**, **Lukt me niet** or **Dit is gedaan**. A decline may be changed to acceptance while the task is available; accepted-task withdrawal is not yet implemented.

The fragment is removed from the visible URL with `history.replaceState`; the token stays only in JavaScript memory and is sent in an Authorization header. It is not put in cookies, localStorage, sessionStorage or request URLs. Reloading therefore requires reopening the original link. The original message/link still contains the capability, and browser extensions, a compromised device or screenshots are outside this protection. Anyone with the link can exercise its scoped rights until expiry or episode closure.

The page renders personal strings as text, uses local assets only, and has a restrictive content security policy, no-store responses, no-referrer policy and framing protection. GET returns no other contact identities or addresses. Conflicts and unknown network outcomes hide stale controls and require a fresh read before further action; no success is displayed without a successful response. Expired/closed/unknown links all return the same generic 404. An already displayed message is not remotely erased at the instant a link expires; the next request enforces expiry.

| Route | Method | Body | Result |
| --- | --- | --- | --- |
| `/help`, `/help.css`, `/help.js`, `/favicon.svg` | GET | None | Fixed non-personal page/assets; no directory serving |
| `/api/v1/recipient` | GET | None | `{data: {message, acknowledged, tasks}}` |
| `/api/v1/recipient/acknowledgment` | POST | `{}` | Records explicit acknowledgment, returns updated recipient view |
| `/api/v1/recipient/task-responses` | POST | `{task_id, action}` | `accept`, `decline` or `complete`; returns updated view |

API calls require `Authorization: Bearer <recipient capability>`. Mutation requests additionally require the exact configured `Origin` and JSON content type. Bodies are limited to 8192 bytes; duplicate keys, unknown fields, wrong types and query strings are rejected. Codes: 400 invalid input, 403 origin/host restriction, 404 unavailable capability/resource, 405 method mismatch, 409 task conflict, 413 body too large, 415 wrong media type, 503 temporary/internal failure (generic message, Retry-After). No CORS access, owner routes, signup or dispatch routes are exposed. The OpenAPI file describes this initial boundary; it is not a generated client or a formal conformance certification.

### Local development listener

After trusted code has provisioned a dedicated store, run from the repo root:

```powershell
./backend/.venv/Scripts/python.exe -m backend.local --database C:/private/autofever/state.sqlite3 --port 8080
```

The path above is illustrative, not an existing provisioned database. `AUTOFEVER_STORE_KEY_HEX` must be supplied privately in the process environment as the store's 32-byte key encoded in 64 hex characters; do not paste it into Git, shared commands, logs or screenshots. The CLI does not generate an owner, create a database, choose a provider, activate an episode or send anything. It refuses missing/symlink databases and nonmatching keys. `make_local_server(store, 0)` is the test entry point for a random loopback port.

This listener binds only `127.0.0.1`, uses exact Host/Origin checks and suppresses request logging, including accidentally pasted query secrets. A top-level navigation from an external message can open the generic page; cross-site API access cannot. The WSGI app itself currently refuses non-loopback origins. Do not forward/tunnel this port or replace the loopback binding to deploy it. The development server is single-process, has a ten-second connection timeout and has **no production rate limiter or edge protection**. See [Python's WSGI development-server documentation](https://docs.python.org/3/library/wsgiref.html#module-wsgiref.simple_server).

## Optional owner connection

Add `--with-owner` to the local listener command and open `/owner`. This serves the existing profile editor with an optional connection module, not a second copy of the app. Provisioning an owner is still a trusted `Store.create_owner()` call; there is no public signup endpoint or automatic message sender. See [owner setup and lifecycle](owner-api.md) for the exact boundary and limitations.

A local Chromium end-to-end test used a disposable database, a separately provisioned test owner and an injected synthetic sender. It exercised one-press activation of the saved profile (not its separate draft), loss of the HTTP response **after the real activation committed**, reload and idempotent retry (one episode, two initial jobs), recipient acknowledgment/acceptance/completion shown to the owner, and loss of the response after recovery committed. Reload reconciled recovery without duplicating jobs, and the recipient link then denied access. There were no external deliveries. The unchanged standalone preview's six browser suites and runner checks also passed. The development test transport intentionally dropped selected responses; normal successful interactions had no console errors. Owner layout was checked at 320, 390 and 1280 CSS pixels.

Remaining required work: production owner provisioning, credential rotation/revocation and safe device credential recovery; production rate limits and HTTP server; production SMTP qualification, real delivery evidence and the other channel adapters; updates, reminders, recurrence, escalation, backup helpers and fallback channels; provider-specific evidence retrieval, failed-job recovery and the nontechnical flow for unresolvable uncertainty; deletion/retention, database backup/restore and key rotation; production dependency/security review; English UI; Linux and shared-host testing; HTTPS deployment on the existing `013-hire-ai` host as `028-autofever`. No new server, paid service, production data, external message or server configuration was used by this work.
