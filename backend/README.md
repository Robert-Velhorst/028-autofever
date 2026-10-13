# Autofever service core

This is the persistent backend component for the notification/help/recovery chain, with owner and recipient web interfaces. The development listener remains **local-only**; a separate [hosted HTTPS-proxy entry point and Hetzner guide](../deploy/README.md) are implemented but not deployed. A concrete [SMTP email adapter and opt-in worker](smtp.md) are implemented and locally tested, but no real provider is configured. The standalone preview still uses only browser storage; the opt-in `/owner` mode connects that same profile editor to the service. Do not expose the development listener to the internet or describe passing tests as external message-delivery evidence.

## Run the tests

Python 3.11 or newer is required. From the repository root, create an isolated environment:

```powershell
python -m venv backend/.venv
./backend/.venv/Scripts/python.exe -m pip install --require-hashes -r backend/requirements.lock
./backend/.venv/Scripts/python.exe -m unittest discover -s backend/tests -v
```

Use CPython 3.11 on 64-bit Windows or Linux; these are the backend targets in [`runtime-matrix.json`](runtime-matrix.json), consumed by GitHub Actions. On Linux, the environment's Python executable is `backend/.venv/bin/python`. `requirements.txt` is the small direct-dependency input; `requirements.lock` pins every resolved dependency and accepted artifact hash for reproducible installation with pip's hash checking. Regenerate it from the direct requirements with `uv pip compile backend/requirements.txt --generate-hashes --python-version 3.11 --output-file backend/requirements.lock`, review the resolved package changes, then test a clean installation on both matrix targets. Tests create disposable SQLite files and synthetic recipients under `.invalid`, generate only test capabilities, and use injected sender functions or temporary loopback TLS SMTP servers. The HTTP integration test also uses an ephemeral loopback listener. No tests contact external providers or read the mobile preview's browser database.

The backend's tested platforms are 64-bit Windows and Linux. The [cryptography security upgrade](dependency-security.md) pins 50.0.2, audits the exact runtime dependencies and verifies compatibility with synthetic records/backups created under 46.0.7. That upstream upgrade no longer supports 32-bit Windows or x86_64 macOS. Platform test counts and remaining deployment gates are maintained in [deployment verification](../deploy/README.md#local-and-linux-verification).

## Implemented boundary

`backend.service.Store` is the authoritative in-process interface. HTTP routes are documented in [OpenAPI](openapi.yaml), with the optional owner flow explained in [the owner contract](owner-api.md). [Private setup commands](provisioning.md) now generate new keys/stores and provide resumable owner enrollment with a private credential file. Provisioning and dispatch remain trusted local operations with no HTTP routes.

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
| `close(owner, episode_id, state, recovery_message=None, recovery_recipients=None)` | `recovered` or `cancelled`; message required for recovery; optional unique recovery-recipient IDs | Stops queued initial notices and outstanding tasks; invalidates action capabilities through episode state. Recovery queues the edited message to the selected subset of recipients whose initial notice was accepted (or all eligible recipients when omitted); an explicit empty subset records recovery without a notice. Cancellation queues none. |
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

Limits are 100 recipients, 100 tasks, 80-character identifiers and 10,000-character core messages (2,000 for preview-profile messages). Unknown fields are rejected rather than silently losing intended behavior. Channels accepted by the core as data are `email`, `sms`, `whatsapp` and `push`. Email has an implemented SMTP adapter; the other channels have no concrete adapters yet, and none is configured for live delivery. Phone destinations require international `+` notation. Preview activation preserves recurrence, backup-helper, check-in, duration and recovery preferences in encrypted `preparation`. The owner API calculates and persists due check-ins; they appear only when the owner opens or refreshes Autofever and do not contact anyone. Recurring help, background reminders and automatic backup/fallback are not executed. One recipient currently has one chosen initial channel. Profiles with multiple selected channels or Push fail before activation rather than silently choosing a destination or discarding channels. Multichannel/fallback and Push remain required work, not removed product requirements.

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

Use a private operator-owned directory, a dedicated key from outside the repository, restricted filesystem permissions and separately protected key backups. Initial POSIX database creation requests mode `0600`; Windows ACLs and parent-directory permissions require operator verification. Owners can delete their live episode records through the owner API; this is logical deletion, not physical media erasure, and does not remove database backups or copies already delivered to recipients. Automatic retention, backup expiry, key rotation and deletion of backups remain operator/release work. The service does not harden preexisting file permissions. It cannot recover encrypted data without the key. Do not point it at Hire.ai's database, secrets or volumes.

Implementation references: [Python SQLite transaction documentation](https://docs.python.org/3/library/sqlite3.html), [cryptography authenticated encryption](https://cryptography.io/en/latest/hazmat/primitives/aead/). These document primitives, not a security certification of Autofever.

The [server backup CLI](backups.md) now creates consistent, separately encrypted SQLite archives, verifies structure and encrypted records, and restores to a new filename with a persistent application hold. Restored copies cannot be opened by the live store, and all data transactions check the hold. Do not remove it or run older code against a restored copy: post-snapshot sends, missing episodes and revoked capabilities require a separate safe-cutover procedure. Automated off-host backups, retention, key recovery and live restore promotion remain open release gates.

## Verification checkpoint — 13 October 2026

The latest hosted-transport test count and platform results are recorded in [deployment verification](../deploy/README.md#local-and-linux-verification). The pre-hosted baseline comprises 86 cases: 24 service, 12 recipient WSGI, eight owner/profile, one real loopback HTTP, ten SMTP unit, 15 SMTP TLS/worker and 16 reconciliation/process-lock cases. Hosted tests add proxy/origin isolation, concurrent rate limits, private credentials and logs, database readiness and a real Waitress socket. Resource warnings are treated as errors.

Coverage includes persistent idempotency, owner/recipient isolation, concurrent activation and job claims, exclusive task claims, private declines, acknowledgments, recovery targeting, cancellation, retries, ambiguous outcomes, worker crash leases, ciphertext substitution, wrong keys, transaction rollback and refusal to modify another application's database. HTTP cases exercise origin/host restrictions, bearer scope, duplicate JSON fields, malformed bodies, size limits, method/path restrictions, generic errors and restart persistence. Owner cases cover lossless preparation, helper outcomes, unsupported-channel rejection and repeatable closure. SMTP cases distinguish acceptance, explicit rejection and lost replies; reconciliation cases include encrypted decisions, bounded explicit retry, rollback, active-sender exclusion, separate-process contention and actual process death. See [SMTP limits](smtp.md#verification) and [reconciliation boundaries](reconciliation.md).

A separate local Chromium browser check exercised the actual HTTP service with disposable synthetic records, without mocked fetch: personal link, explicit acknowledgment, accept/decline/complete, second-helper conflict, offline error/reload recovery and missing/invalid-link states. Page identity, meaningful content, absence of framework overlays, clean successful-flow console, same-origin requests, stripped URL fragments, empty browser storage and screenshots were checked at 320, 390 and 1280 CSS-pixel widths. Deliberately induced offline/404/409 responses are expected errors, not successful operations. This is not physical-phone, Safari, screen-reader or production evidence.

## Recipient web interface

The page at `/help#RECIPIENT_CAPABILITY` shows only that recipient's message and assigned tasks, with a Dutch/English interface toggle. The owner profile and management interface also offer Dutch/English interface text, with the preference stored locally in that browser. These toggles translate interface labels and status text, not sender-authored messages or other personal content. No account, app installation or owner capability is needed for a recipient. Opening the page or fetching data does **not** acknowledge the message. The reader explicitly chooses **Ik heb dit gelezen / I have read this**, **Ik pak dit op / I can help**, **Lukt me niet / I cannot help** or **Dit is gedaan / This is done**. A helper who accepted a task can now withdraw that commitment; the task returns to pending for other assigned helpers, the withdrawing helper is recorded as unable to help, and no one is automatically notified. The helper may still accept it again while it remains available.

The fragment is removed from the visible URL with `history.replaceState`; the token stays only in JavaScript memory and is sent in an Authorization header. It is not put in cookies, localStorage, sessionStorage or request URLs. Reloading therefore requires reopening the original link. The original message/link still contains the capability, and browser extensions, a compromised device or screenshots are outside this protection. Anyone with the link can exercise its scoped rights until expiry or episode closure.

The page renders personal strings as text, uses local assets only, and has a restrictive content security policy, no-store responses, no-referrer policy and framing protection. GET returns no other contact identities or addresses. Conflicts and unknown network outcomes hide stale controls and require a fresh read before further action; no success is displayed without a successful response. Expired/closed/unknown links all return the same generic 404. An already displayed message is not remotely erased at the instant a link expires; the next request enforces expiry.

| Route | Method | Body | Result |
| --- | --- | --- | --- |
| `/help`, `/help.css`, `/help.js`, `/favicon.svg` | GET | None | Fixed non-personal page/assets; no directory serving |
| `/api/v1/recipient` | GET | None | `{data: {message, acknowledged, tasks, updates}}`; updates are scoped to this recipient |
| `/api/v1/recipient/acknowledgment` | POST | `{}` | Records explicit acknowledgment, returns updated recipient view |
| `/api/v1/recipient/task-responses` | POST | `{task_id, action}` | `accept`, `decline` or `complete`; returns updated view |

API calls require `Authorization: Bearer <recipient capability>`. Mutation requests additionally require the exact configured `Origin` and JSON content type. Bodies are limited to 8192 bytes; duplicate keys, unknown fields, wrong types and query strings are rejected. Codes: 400 invalid input, 403 origin/host restriction, 404 unavailable capability/resource, 405 method mismatch, 409 task conflict, 413 body too large, 415 wrong media type, 503 temporary/internal failure (generic message, Retry-After). No CORS access, owner routes, signup or dispatch routes are exposed. The OpenAPI file describes this initial boundary; it is not a generated client or a formal conformance certification.

### Local development listener

After trusted code has provisioned a dedicated store, run from the repo root:

```powershell
./backend/.venv/Scripts/python.exe -m backend.local --database C:/private/autofever/state.sqlite3 --port 8080
```

The path above is illustrative, not an existing provisioned database. `AUTOFEVER_STORE_KEY_HEX` must be supplied privately in the process environment as the store's 32-byte key encoded in 64 hex characters; do not paste it into Git, shared commands, logs or screenshots. The CLI does not generate an owner, create a database, choose a provider, activate an episode or send anything. It refuses missing/symlink databases and nonmatching keys. `make_local_server(store, 0)` is the test entry point for a random loopback port.

This listener binds only `127.0.0.1`, uses exact Host/Origin checks and suppresses request logging, including accidentally pasted query secrets. A top-level navigation from an external message can open the generic page; cross-site API access cannot. The default WSGI development mode refuses non-loopback origins. Do not forward/tunnel this port or replace the loopback binding to deploy it. The development server is single-process, has a ten-second connection timeout and has **no production rate limiter or edge protection**. See [Python's WSGI development-server documentation](https://docs.python.org/3/library/wsgiref.html#module-wsgiref.simple_server). Hosted deployment uses the separate `backend.hosted` transport with authenticated proxy checks, Waitress limits and request quotas, described in [the deployment guide](../deploy/README.md); those additions do not turn the development listener into a production server.

## Optional owner connection

Add `--with-owner` to the local listener command and open `/owner`. This serves the existing profile editor with an optional connection module, not a second copy of the app. Use the [private provisioning CLI](provisioning.md) for durable, resumable owner enrollment; `Store.create_owner()` remains available to trusted programmatic callers. There is no public signup endpoint or automatic message sender. See [owner setup and lifecycle](owner-api.md) for the exact boundary and limitations.

A local Chromium end-to-end test used a disposable database, a separately provisioned test owner and an injected synthetic sender. It exercised one-press activation of the saved profile (not its separate draft), loss of the HTTP response **after the real activation committed**, reload and idempotent retry (one episode, two initial jobs), recipient acknowledgment/acceptance/completion shown to the owner, and loss of the response after recovery committed. Reload reconciled recovery without duplicating jobs, and the recipient link then denied access. There were no external deliveries. The unchanged standalone preview's six browser suites and runner checks also passed. The development test transport intentionally dropped selected responses; normal successful interactions had no console errors. Owner layout was checked at 320, 390 and 1280 CSS pixels.

The [private owner access CLI](owner-access.md) can now replace a retained credential while preserving the same account, or revoke the exact code. This advances database compatibility to at least version 2 (preserving version 3 when present), denies old codes on subsequent requests, supports explicit interruption recovery and preserves queue/helper state. Stop all older Autofever processes before first use; do not downgrade the database or runtime afterward. No public rotation/recovery endpoint is introduced.

[Explicit updates](updates.md) now connect the owner editor, selected informed recipients, idempotent API, encrypted queue, SMTP sender and recipient-specific history. New stores use database version 3; existing v1/v2 stores need the separate backup-first migration. Local browser tests include lost replies after commit and safe switching between helper links in one tab. Scheduled reminders and automatic updates are not implemented by this feature.

[Optional server-history retention](retention.md) is owner-configurable, encrypted, disabled by default and limited to old closed episodes with no queued, active or uncertain send. A bounded daily cleanup CLI and systemd template are provided; they are not installed or verified on the Hetzner host. Off-host backup expiry remains separate.

Remaining required work: target-host provisioning acceptance, nontechnical onboarding/credential transfer and safe device recovery when credential copies are lost; target-host HTTP/HTTPS, unit, proxy, logging, capacity and load acceptance; production SMTP qualification, real delivery evidence and the other channel adapters; recurrence, escalation, backup helpers and fallback channels; provider-specific evidence retrieval, failed-job recovery and the nontechnical flow for unresolvable uncertainty; off-host backup expiry/erasure, key recovery/rotation and safe live restore promotion; production dependency/security review; physical-device and shared-host testing; HTTPS deployment on the existing `013-hire-ai` host as `028-autofever`. V1 check-ins remain in-app-only: a due check-in appears only when the owner opens or refreshes Autofever, and no helper or background notification is sent. The profile/owner and recipient interfaces now offer Dutch/English interface text; personal content is preserved. Owner controls can export encrypted server history and logically delete live server episode records; they do not erase sent messages or operator-held copies. Local Linux container tests are not target-host acceptance. No new server, paid service, production data, external message or server configuration was used by this work.
