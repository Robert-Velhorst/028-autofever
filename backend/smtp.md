# SMTP email delivery

Autofever now has a concrete SMTP adapter and queue worker. They have been tested against disposable **local TLS SMTP servers**, not a real mailbox provider. No external email was sent, no SMTP account was configured, and no paid service was selected. Production delivery and public recipient links are not yet qualified.

## What is implemented

- `SMTPSender` follows the existing `Store.dispatch_one` contract, with no second queue or retry architecture.
- Explicit implicit TLS or STARTTLS; certificate trust, hostname verification and TLS 1.2+ are required. No plaintext mode or insecure-certificate switch exists. Authentication occurs only after TLS, and STARTTLS is followed by another EHLO.
- One envelope recipient and one `To` header per job; no CC/BCC, tracking pixels, HTML, attachments or other recipients' information.
- UTF-8 text is MIME-encoded; illness emails contain that recipient's private `/help#CAPABILITY` link. Recovery emails contain no reusable help capability.
- A stable `Message-ID` is derived from the queue job ID and configured sender domain. This is a trace reference, **not provider-side idempotency** or a guarantee against duplicate delivery.
- An explicit operator recipient allowlist is checked before any network connection. A non-allowlisted or unsupported mailbox is a definite failed attempt, not silently rerouted mail. The worker selects only email jobs; other channels are not consumed or marked sent. Existing queue maintenance may still expire old jobs or quarantine expired leases.
- Bounded runs or an opt-in continuous worker. Retries remain subject to the queue's persisted due time and five-attempt limit. Transient SMTP failures stop a bounded batch or introduce a 30-second worker cooldown; this prevents immediately trying every queued message against the same temporary fault.
- Authentication failures and permanent account/TLS/sender configuration faults halt the worker after recording the current job outcome. Remaining jobs are not consumed with the same known-bad credentials. Correct configuration and inspect outcomes before restarting; no automatic status reset or blind replay is provided.

## Configuration and credentials

[smtp.example.json](smtp.example.json) is illustrative and intentionally uses `.invalid` domains. It cannot deliver email. Copy its shape into a private operator-owned file **outside the repository** and supply real settings only after a sender/provider has been authorized. Restrict parent-directory and file access; Windows ACLs and Linux permissions are operator responsibilities. No automatic `.env` loading occurs.

| Field | Meaning |
| --- | --- |
| `host` | Explicit SMTP hostname or IP, chosen by the operator; never taken from an HTTP request |
| `port` | Explicit integer 1–65535; commonly 465 for implicit TLS or 587 for STARTTLS, subject to the chosen provider |
| `security` | Exactly `implicit_tls` or `starttls` |
| `username` | Dedicated SMTP username, not a browser user's app password |
| `from_address` | Single authorized plain ASCII mailbox; sender domain also forms the stable Message-ID |
| `help_origin` | Verified public HTTPS Autofever origin, without path, trailing slash, query, credentials or fragment |
| `allowed_recipients` | Explicit list of approved plain ASCII email addresses; not a wildcard or consent inferred from imported contacts |

Manual CLI invocations may privately supply:

- `AUTOFEVER_SMTP_PASSWORD`: SMTP credential, never written to the JSON file or a command argument.
- `AUTOFEVER_STORE_KEY_HEX`: the existing dedicated store's 32-byte key, encoded as 64 hex characters.

The CLI also accepts both credentials as private files with `--store-key-file` and `--smtp-password-file`; use both flags together. Files must be regular, nonsymlink, bounded, and inaccessible to group/other users on POSIX. The key file contains 64 lowercase hexadecimal characters, optionally followed by a newline; the password file contains the ASCII password and may have one final newline. SMTP configuration is likewise required to be a private regular file. These file options are intended for systemd's credential directory and avoid placing secrets in process arguments or environment variables. Mixing file and environment credentials fails closed.

The CLI removes environment credentials after reading them; file credentials necessarily remain in process memory while needed. Do not print environment values, enable SMTP debug output or attach real message/credential dumps to bug reports. Python/system instrumentation and provider logs are outside the application's no-logging guarantee. Config object representations do not expose fields. SMTP errors are mapped to generic outcomes; provider response text, credentials and message bodies are not persisted as diagnostic strings.

The supported mailbox subset excludes display names, quoted local-parts, internationalized mailbox addresses and SMTPUTF8. Message bodies themselves support Unicode. SMTP credentials are currently ASCII. These restrictions fail explicitly; addresses are not transliterated or guessed. Sender identity/domain authorization, recipient consent and provider conditions still require operator review.

## Commands

Run from the repository root, using the existing virtual environment. The paths below are examples, not provisioned files. For Linux replace the Python executable with `backend/.venv/bin/python`.

Local checks only:

```powershell
./backend/.venv/Scripts/python.exe -m backend.worker --database C:/private/autofever/state.sqlite3 --smtp-config C:/private/autofever/smtp.json --check
```

When using private credential files instead of environment values:

```powershell
./backend/.venv/Scripts/python.exe -m backend.worker --database C:/private/autofever/state.sqlite3 --smtp-config C:/private/autofever/smtp.json --store-key-file C:/private/autofever/store-key --smtp-password-file C:/private/autofever/smtp-password --check
```

This checks the existing store/key and configuration shape. It performs **no network calls and no queue consumption**. It does not verify provider credentials, account permissions, the public app URL, allowlist coverage of saved profiles, DNS authentication, inbox receipt or production readiness.

Only after the external-sending prerequisites below are satisfied, an operator can explicitly enable a bounded run:

```powershell
./backend/.venv/Scripts/python.exe -m backend.worker --database C:/private/autofever/state.sqlite3 --smtp-config C:/private/autofever/smtp.json --send --max-jobs 1
```

Or run continuously until stopped:

```powershell
./backend/.venv/Scripts/python.exe -m backend.worker --database C:/private/autofever/state.sqlite3 --smtp-config C:/private/autofever/smtp.json --send --continuous --poll-seconds 5
```

There is no implicit send mode. Without `--check` or `--send`, the CLI refuses to run. Bounded mode defaults to one attempt and accepts at most 100. Exit 0 means the invocation finished, **not that messages were delivered**. Exit 2 is local configuration/argument failure; exit 3 requires SMTP account/configuration attention; exit 1 is an internal worker failure. SIGINT/SIGTERM request a graceful stop after the current attempt. A forced process kill leaves the existing lease mechanism to quarantine uncertain work.

Continuous mode processes already queued illness, recovery and [explicit update](updates.md) emails; it does **not** send check-in reminders, run recurring tasks, escalate to backup helpers, create automatic updates or use fallback channels. Owner check-ins are in-app only and require the owner to open Autofever. Update emails have their own stable queue/Message-ID and subject, one private recipient, plain text and no renewed personal link. Use one SMTP worker per configured account until a shared account-level rate limiter has been implemented. Per-process cooldown is not a distributed quota mechanism.

An optional [systemd worker template](../deploy/028-autofever-worker.service) runs the existing CLI continuously with explicit `--send`, using private systemd credentials for the store key, SMTP password and SMTP configuration. It is not installed or enabled by this repository. Do not start or enable it until the provider/account, sender identity, approved recipient allowlist, public help origin, credentials and delivery procedures are qualified. Enabling it authorizes queued explicit illness, recovery and update emails to be sent; it does not authorize check-in reminders because no check-in jobs are created.

## Delivery-state semantics

| Observation | Persisted outcome |
| --- | --- |
| Final positive DATA `250` received | `accepted`; not `delivered` or `acknowledged` |
| Definite SMTP 4xx rejection | `queued` with bounded retry delay, eventually `failed` after the configured attempt limit |
| Definite SMTP 5xx rejection or invalid/unauthorized envelope | `failed`; no automatic replay |
| Disconnect before body submission starts | Retryable definite non-acceptance |
| Disconnect/timeout after body submission starts, including loss of the final reply | `uncertain`; never automatically replayed |
| Unexpected final protocol response | Conservatively `uncertain` |
| QUIT/connection cleanup fails after positive acceptance | Remains `accepted` |

The stored receipt is an encrypted `smtp-accepted:<Message-ID>` **local acceptance reference**, not a provider-issued delivery receipt. Raw SMTP response text is deliberately not retained. The adapter uses ten-second socket-operation timeouts; DNS resolution and the entire transaction are not governed by a single deadline. These initial submission timeouts must be qualified with the selected provider: a slow post-DATA reply can be quarantined even when the provider later delivers. The existing five-minute queue lease is not a delivery SLA.

Protocol references: [Python SMTP client documentation](https://docs.python.org/3.11/library/smtplib.html), [RFC 5321, reply semantics after DATA](https://www.rfc-editor.org/rfc/rfc5321#section-4.2.5). SMTP acceptance transfers responsibility to the receiving server; later delivery can still fail. Lost replies are one reason not to promise exactly-once delivery. This implementation intentionally quarantines ambiguity instead of relying on Message-ID deduplication.

## Before any external sending

1. Authorize the actual provider/account, sender identity and allowed recipients. Check any costs or service commitments separately; none has been approved or incurred here.
2. Qualify the [separate hosted transport](../deploy/README.md) and deploy Autofever separately on the existing `013-hire-ai` host. The development listener intentionally refuses public origins. Do not publish/forward it or weaken those guards to make an email link work. The hosted entry point and Linux tests are implemented, but actual public HTTPS and shared-host acceptance remain unverified.
3. Verify the real public `/help` URL, capability expiry, TLS, recipient privacy and mobile behavior. `help_origin` validation checks syntax only; it cannot prove a deployed app exists.
4. Verify the chosen provider's authentication, domain authorization, limits and security requirements. There is no automatic DNS modification or provider signup.
5. Perform a separately authorized test to an approved real address and inspect actual receipt, failures and recovery. Local SMTP tests are not that proof.
6. Qualify the [private uncertain-send review procedure](reconciliation.md) with the chosen provider, including how to obtain authoritative evidence. Complete credential rotation, backup/restore, retention, monitoring and operator procedures. Only after these gates should the operator install and enable the optional worker unit. A failed or uncertain job is never reset by editing SQL to force another send. Explicit requeue through the review tool is allowed only after verified non-acceptance and still enforces attempt/expiry limits. The current UI reports queue status but is not a live provider-configuration dashboard.

TLS secures the connection to the SMTP server, not end-to-end confidentiality. The provider and intended recipient can read message content and the personal link. Keep disclosures minimal; do not include a diagnosis unless deliberately configured by the user. Verify link handling in real email clients before production acceptance.

## Verification

Tests use local loopback sockets, temporary test certificates and synthetic `.invalid` recipients only. They exercise implicit TLS, STARTTLS before AUTH, rejection of untrusted/mismatched certificates and missing STARTTLS, MIME/Unicode/dot-stuffing, single-recipient scope, stable Message-ID, late disconnects, definite retry, durable uncertainty, account-failure suspension, worker cooldown and graceful stop, email-only queue selection and recovery without a reusable link. The configuration-check CLI is verified not to connect or consume a job; file-based credentials are tested against the local synthetic server. The deployment unit is checked for explicit send mode, systemd credential injection and its dedicated writable path. Existing lifecycle/HTTP/browser-source tests remain separate evidence; live delivery, inbox placement, bounce callbacks and provider acceptance are unverified.
