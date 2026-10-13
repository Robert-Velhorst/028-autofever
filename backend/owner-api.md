# Local owner connection

This is an opt-in development path, **not deployed production authentication**. Start the loopback listener with `--with-owner` and visit `/owner`. Without this option all owner routes and assets are absent. `/help` remains the separate recipient page. The same local-server restrictions in [README](README.md) apply: no port forwarding, public reverse proxy or production credentials.

The same owner interface and capability contract are also used by the separate [hosted entry point](../deploy/README.md), which adds authenticated proxy checks and rate limits. That path is tested locally but not deployed. The local instructions below do not authorize exposing the development listener.

## Setup and authority

A trusted operator can now use the [private setup CLI](provisioning.md) to initialize a new dedicated store and provision owner access into a private credential file. Interrupted enrollment is explicitly resumable using that same file; it does not print the code or create a second owner on replay. Only the capability hash and an encrypted enrollment audit are stored in the database. `Store.create_owner()` remains a lower-level trusted API that returns the raw capability once; callers are responsible for persisting it safely. Transfer only the capability privately. Do not put it in a URL, Git, shared logs or screenshots. The browser's **Instellingen → Lokale server koppelen** form checks it against the configured same-origin server before storing it. No email/password account or recipient login is introduced. Nontechnical onboarding/transfer and recovery remain required production work.

Choose a visible helper-link lifetime of 1–168 hours at setup. Changing it affects new episodes only. The HTTP/core contract accepts an explicit 60–604800 seconds. The capability is stored in a separate encrypted IndexedDB record, using the existing browser key; that key is on the same device. This does not protect an unlocked browser, a compromised device or same-origin script execution. Owner capability rotation, revocation and device-loss recovery are not implemented yet. Browser profile backups deliberately exclude the connection record and pending server operation; restoring a profile backup does not mutate, cancel or recover an existing server episode. Do not clear browser storage when an action's outcome is unknown.

The server injects a same-origin connection module into the existing HTML. Exact hashes authorize its existing inline script; the owner page permits inline styles required by the existing layout. The recipient page retains its stricter no-inline-script/no-inline-style CSP. Both pages are one origin; this is not a cross-origin security-isolation claim. The source preview remains usable standalone, with no networking or server activation when the connection module is absent.

## One-press activation and uncertain outcomes

1. Prepare contacts and save the default profile in the existing editor. Drafts remain separate.
2. **Ik ben ziek** reads the saved record and refuses a detected stale-tab revision. There is no second confirmation.
3. Before making an HTTP request, store a random command identifier and immutable selected profile/contact payload in the encrypted connection record. A conflicting connection revision fails before sending.
4. The server validates the full profile, snapshots the original preparation, and atomically creates the episode, help tasks, recipient capabilities and outgoing jobs.
5. Record success only after a successful server response. Unknown/network outcomes preserve the same command and payload across reload. **Uitkomst controleren** retries that same idempotent command, never a newly generated illness request. Definitive validation/conflict responses permit correction; they do not show success.
6. **Serverstand ophalen** reads the authoritative last episode, acknowledgments, help claims/completion and outgoing queue states. It does not send messages. There is no automatic polling/push subscription yet; labels explicitly describe the last checked state.

One recipient currently needs exactly one Email, SMS or WhatsApp channel. There is no arbitrary first-channel selection, invented Push address, or automatic fallback. Multiple selected channels and Push fail before activation. International phone numbers require `+countrycode`; formatting spaces, dots, parentheses and hyphens are normalized without inventing a country code. This limitation does not remove multichannel/fallback from the product scope.

All supported preview fields are preserved: profile ID/name, general and per-person messages, recovery text, expected return, check-in interval, selected recipient order, selected contacts, and each task's ID/title/description/helpers/time/repeat/backup. Unknown fields are rejected rather than ignored. Task descriptions reach only assigned recipients. Preparation and all contact destinations are visible only through owner access, not recipient APIs. Repeat/check-in/backup preferences are shown as stored but **not scheduled/executed**. Updates are not yet sent from this mode; the standalone preview's update editor remains local-only.

## Recovery and cancellation

**Ik ben hersteld** uses the recovery text frozen with the active episode. Recovery closes the episode and queues a recovery notice only for recipients whose initial notice was positively accepted by the sender. Acceptance is not delivery or reading. **Gebeurtenis annuleren** closes without recovery notices. Both invalidate recipient access through episode state and close unfinished tasks.

The closing request is persisted before submission. A lost response is reconciled against the latest episode after reload, or the identical terminal operation can be retried. A new illness episode is refused while prior outgoing work is queued/in flight/uncertain. Closing while a send is in flight or uncertain is also refused. A [private operator tool](reconciliation.md) can settle an uncertain attempt using externally verified provider evidence; the owner bearer cannot invoke it. Refreshing then shows the resulting ordinary queue state. Unresolvable uncertainty and a nontechnical support flow remain required work; never bypass the guards by editing SQL statuses. A definite 409 does not retain a misleading successful operation.

## HTTP contract

All routes require an owner bearer capability, exact Host, same-origin mutation requests, no query strings and no cookies. An unknown, recipient or other-owner capability cannot read or close an owner's record. No public owner creation or sender-dispatch routes exist. [OpenAPI](openapi.yaml) includes the transport shapes.

| Route | Method | Input | Success |
| --- | --- | --- | --- |
| `/api/v1/owner/episode` | GET | No body | `{data: null}` or most recently created own episode, including terminal state |
| `/api/v1/owner/episodes` | POST | Exactly `command`, `profile`, `contacts`, `link_ttl` | 200 with the episode, both on first activation and idempotent replay |
| `/api/v1/owner/episode-closures` | POST | Exactly `episode_id`, `state`, `recovery_message` | 200 with updated episode; cancellation requires a null recovery message |

An episode response has `id`, `state`, immutable `snapshot`, `notifications` (`id`, `recipient`, `kind`, `status`, `attempts`), `recipients` (`id`, `acknowledged`) and `tasks` (`id`, `state`, `claimant`, `declined_by`). Never raw recipient links, sender receipts, owner capabilities or database details. An owner may see the identities of their own helpers; another recipient may not.

Activation bodies have a 2 MiB limit, other mutations 8192 bytes. Shared error codes: 400 invalid/unsupported input, 403 host/origin mismatch, 404 unavailable access, 405 wrong method, 409 conflicting state, 413 size, 415 non-JSON, 503 generic internal/temporary error. Error text does not interpolate input or exceptions. No production rate limiter is implied.
