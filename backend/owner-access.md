# Replace or revoke an owner's access code

The private operator CLI can replace an existing owner code without creating a
different account, or disable a particular code without deleting account data.
This is useful when a phone is lost **and the trusted operator still has the
corresponding private credential file**. It is not public password recovery,
identity verification, remote device wiping or a finished mobile recovery flow.

The CLI never opens a listener, activates an episode, contacts a provider or sends
a message. Existing episodes, helper responses, queue jobs, idempotency commands
and scoped helper links are preserved. Replacing access does not reverse actions
already authorized before replacement, cancel queued notifications, erase data
already displayed on a lost device or revoke recipient links.

## Before use: forward-only database compatibility

1. Use only dedicated `028-autofever` files, never Hire.ai's state or services.
2. Stop **all Autofever application processes running older code**, including
   web, worker and local listeners. Deploy this access-aware release to every
   Autofever process before using these commands. Do not run mixed versions.
3. Preserve a verified encrypted backup and separately protected key and owner
   credential files. An old backup is not a way to undo revocation safely.
4. Verify trusted private directories, POSIX permissions/Windows ACLs, canonical
   database path and operator authority. An operator possessing the database and
   store key is already privileged; these commands do not verify a person's
   real-world identity or provide an additional authentication factor.

New and untouched databases remain at `PRAGMA user_version=1`. The first
successful rotation or revocation advances the version to **2 in the same SQL
transaction** as the access changes. Tables and episode owner IDs are unchanged;
encrypted `owner-access:<capability hash>` records map replacement credentials
to a stable owner and retain disabled-code records. No episode/queue rewrite or
data deletion is performed. Existing v1 credentials remain supported unless
explicitly disabled.

Version 2 is an **irreversible compatibility floor**, not a reversible feature
flag. Older releases refuse that version at startup. Already-running old code
cannot be made safe by a version marker alone, which is why stopping it first is
mandatory. Never lower the version, remove access records or run an old release
against this state. Fix forward with access-aware code; preserve revocation and
send history. The upgraded backup verifier accepts v1/v2 and validates access
record structure and owner binding; older verifiers refuse these databases.

## Replace a code while retaining the account

Use the configured backend interpreter from the repository root. These are
illustrative paths, not a completed server deployment:

```sh
python -m backend.owner_access rotate --database /var/lib/028-autofever/state.sqlite3 --key-file /etc/028-autofever/store-key --credential-file /private/autofever-access/owner-001.afowner --output /private/autofever-access/owner-001-replacement.afowner
```

The existing credential file is authenticated and checked against its committed
registration. A fresh random replacement is durably published to a **new** private
file before the old code is disabled and the new code enabled atomically. The
new file is version 2, authenticated against the store key/path, stable owner and
previous capability hash. Its capability remains plaintext inside the private
file; authentication is not file encryption. No code is printed.

Verify the replacement using the existing provisioning command:

```sh
python -m backend.provision check-owner --database /var/lib/028-autofever/state.sqlite3 --key-file /etc/028-autofever/store-key --credential-file /private/autofever-access/owner-001-replacement.afowner
```

Privately transfer only its `capability` value to the owner and reconnect via
the existing owner connection form. Never share the store key or whole file,
place a capability in a URL, or paste it into a shared log/chat. Replacement
does not synchronize contacts/drafts stored only on the missing device; the
server account and episode history are preserved, while local preparation
recovery uses the separate browser export mechanism. Device transfer and the
physical-phone recovery experience still require implementation/acceptance.

The old code receives the same generic unavailable response as any invalid
capability on subsequent owner API requests. Other owners and helper access
are not changed. Further replacements use the latest private credential file.

### Interrupted rotation

Preserve both files and the database. An error may occur after the output file
has already been published. Do not invent another filename to retry blindly.
After inspecting the paths privately, run the **same** command with `--resume`.

Resume authenticates both files and either completes the uncommitted operation
or verifies the already committed replacement. It never generates another code.
If another rotation or revocation has superseded either relevant code, stale
resume refuses rather than resurrecting it. A transaction failure rolls back
both access changes and the version advance; a pending file alone grants no
access. Existing output files are never overwritten. Missing or damaged files
are not regenerated; no `--force` option exists.

## Disable a code without creating a replacement

```sh
python -m backend.owner_access revoke --database /var/lib/028-autofever/state.sqlite3 --key-file /etc/028-autofever/store-key --credential-file /private/autofever-access/owner-001-replacement.afowner
```

This disables **that exact code**, not all credentials of an account. Repeating
it is safe; revoking an already replaced old code does not disable its successor.
Revocation can leave the owner without active access. There is deliberately no
automatic re-enable command. Prefer rotation when continued account access is
needed. Deleting a file or disconnecting a browser does not revoke its code.

The command does not cancel an episode or stop the delivery worker. If incident
response requires stopping delivery, that is a separate explicit operator action
with its own in-flight delivery/reconciliation considerations. Do not assume
revocation recalls messages or clears a stolen phone.

All successful commands exit `0`; failures exit `2` with a generic diagnostic
without credentials or record content. Never put raw secrets in command-line
arguments. Enrollment replay cannot re-enable the original code, and a replacement
file cannot be passed as a new owner enrollment.

## Remaining limits and verification

- The input credential file and correct store key are required. Recovery when
  every copy is lost, identity proof, an owner self-service UI and safe transfer
  are unfinished. Creating a new owner is not recovery of an existing one.
- Access records describe current credential state and file binding, not a full
  immutable operator action log. Key rotation, retention and account deletion
  are separate work. Trusted local storage/parent directories remain required.
- Restore copies remain quarantined; no command bypasses `restore-hold`.
  Restoring old data may revive old codes, so live restore promotion is still
  blocked pending review of the entire post-backup interval.
- Tests use synthetic disposable stores: stable history and activation replay,
  old-code denial, cross-owner isolation, chained replacement, explicit resume,
  revoke idempotency, publication/SQL failures, competing rotations, process
  death during the SQL transaction, backup quarantine and actual loopback HTTP.
  No production credentials, providers, physical phones or Hetzner services
  are exercised. See the [platform checkpoint](../deploy/README.md#local-and-linux-verification).
