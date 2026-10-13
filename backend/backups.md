# Server backups and quarantined recovery

This guide is for the trusted Autofever operator, not a recipient. It concerns
only the dedicated `028-autofever` SQLite store. Never use Hire.ai's database,
credentials or directories. Browser profile exports are a different backup:
they do not contain server episodes, delivery outcomes or owner credentials.

## What is available

`python -m backend.backup` can:

- **create** a consistent, encrypted server archive without modifying the source
  database's application records;
- **verify** the archive's authentication, expected schema, SQLite integrity,
  foreign keys and every encrypted record;
- **restore-copy** into a **new filename**, preserving the source and archive,
  with a persistent block on application access and sending.

This is a working recovery-copy and verification tool, **not a live recovery
cutover**. There is no command to remove the restore block. Automated scheduling,
off-host storage, retention, separately protected key recovery and production
restore/cutover acceptance still need implementation or operator setup. None has
been configured on Hetzner by this change.

## Why a restored copy cannot immediately go live

Suppose a backup records a notification as queued. The provider accepts it five
minutes later, then the server is lost. Replaying the old queue could notify that
person twice. Jobs and episodes created after the snapshot may be absent entirely;
changing only the old `sending` jobs to `uncertain` would not solve this. Old
personal links could also have been revoked or closed since the snapshot.

Therefore every restored copy contains an authenticated `restore-hold` record
**before the file is published**. Current application code refuses to open such
a store, and every live store transaction also checks for the marker. This blocks
owner/recipient reads and writes, activation, recovery, cancellation, dispatch
and reconciliation. An already-constructed web process returns a generic 503 for
data requests and private health checks. Generic static pages contain no private
records and may still load; that is not readiness. The hold persists across
restarts, and even a damaged hold blocks use. Offline verification remains
available. Existing queue statuses are preserved as historical evidence, not
rewritten to pretend delivery did or did not happen.

**Do not delete the marker, run SQL to release it, copy the database over a live
path or run an older application release against it.** Older releases do not know
about the hold. The marker is an application safety boundary, not protection
against an operator with filesystem/key access or malicious software.

A future cutover procedure must account for provider evidence, the interval
after the snapshot, missing episodes, revoked capabilities and owner-device
pending commands. It must also prevent two independent stores from sending.
The existing [uncertain-attempt reconciliation tool](reconciliation.md) alone
does not establish that an old snapshot is safe to resume.

## Private prerequisites

Use the supported Python environment from [backend setup](README.md) and run
commands from the repository root. Provide:

1. The existing dedicated Autofever database and its actual 32-byte operator key.
2. A private ASCII key file containing exactly 64 lowercase hexadecimal
   characters, optionally followed by whitespace. POSIX group/other permissions
   are refused; use mode `0600`. Keep the key out of command arguments, shell
   history, Git, the archive directory and logs. Its **path** is an argument.
3. Existing private input/output/working directories on trusted **local** storage.
   Restrict POSIX directory access and independently check Windows ACLs. Ancestor
   directory security is an operator prerequisite, not automatically repaired.
4. Enough space for the source, archive and temporary snapshot, and memory for
   several copies of the bounded snapshot during encryption. The initial limit
   is **64 MiB of database pages**, not an unlimited production backup solution.
   Capacity and peak memory have not been qualified on the shared host.
5. Current Autofever processes using one canonical database path and the shared
   dispatch lock. A backup refuses an active sender/reconciler; it does not stop
   or kill either. Retry later with a new output name after inspecting any
   existing output. A lock file's existence does not mean a process owns it;
   never delete the lock file to bypass ownership.

Regular source/archive files must not be symlinks or have multiple hard links.
Output filenames must not already exist, even as broken symlinks; database
sidecars at the proposed output name are also refused. Publication requires
local filesystem hard-link support. Network filesystems, untrusted directories,
concurrent replacement of source paths and older workers are unsupported.

## Commands

These paths are **examples**, not already provisioned directories. `python` means
the configured backend interpreter (on Windows, for example,
`./backend/.venv/Scripts/python.exe`). Each command is separate; proceed only after
checking the preceding exit status and output.

```sh
python -m backend.backup --key-file /etc/028-autofever/store-key create --database /var/lib/028-autofever/state.sqlite3 --archive /private/autofever-backups/checkpoint-001.afbackup

python -m backend.backup --key-file /etc/028-autofever/store-key verify --archive /private/autofever-backups/checkpoint-001.afbackup --work-directory /private/autofever-review

python -m backend.backup --key-file /etc/028-autofever/store-key restore-copy --archive /private/autofever-backups/checkpoint-001.afbackup --database /private/autofever-review/checkpoint-001.sqlite3
```

The CLI returns `0` for the specific successful operation and `2` on refusal or
error, with a generic diagnostic that does not print record content, keys or
tracebacks. A successful `verify` is not evidence of current delivery, correct
provider configuration, successful key disaster recovery or safe live cutover.
The private Python API additionally returns table counts and archive creation
start time; it does not return personal records. This start time is a conservative
beginning of the snapshot interval, not an exact delivery-history cutoff.

Preserve the verified archive and keep its key in a **separately protected,
recoverable location**. The archive does not contain the key, raw owner login
capability, SMTP password or proxy key. A missing store key makes its encrypted
content unrecoverable. Credentials/provisioning require their own recovery plan.
Do not upload an archive or key to a public issue or repository.

## Snapshot, format and failure behavior

The implementation uses the [Python SQLite backup
API](https://docs.python.org/3.11/library/sqlite3.html#sqlite3.Connection.backup),
including committed WAL state, rather than copying a live main file. Other app
transactions can continue. The result is a consistent historical snapshot, not
necessarily the state at command completion. Backup acquisition and offline
verification each have a 30-second cooperative work budget; these are not hard
wall-clock guarantees against a stalled OS/filesystem. A busy/oversized store
fails instead of producing an archive advertised as complete.

Archive v1 contains the fixed `AUTOFEVER-BACKUP` marker plus version byte `01`,
a random 12-byte nonce and AES-256-GCM ciphertext/tag. The encrypted payload is an
8-byte unsigned big-endian Unix backup start time followed by the SQLite snapshot.
HKDF-SHA256 derives a separate archive key from the operator key using
`autofever:backup:v1`; the header is authenticated associated data. This wraps
the database's already-encrypted records and also hides its relationship/state
metadata. Archive size and filesystem timestamps are not hidden. The operator
and running application can decrypt data; this is **not end-to-end encryption**.

Verification refuses unknown database/application versions, schema changes,
missing indexes, unexpected views/triggers, corrupt relationships, missing key
checks, unknown metadata and failed record authentication. It verifies episode
snapshot shape and encrypted job identities too. It is not a full semantic
business-state proof, protection from a key-holding attacker, or provider-history
reconciliation. The exact v1 schema comparison is intentionally strict: future
schema changes need an explicit supported backup/restore version.

Temporary snapshots live in restricted, uniquely named directories under the
chosen output/working directory, not inside Hire.ai or a shared database. They
retain the ordinary database's visible metadata; handle them as private data.
Normal success/error cleanup removes only these owned temporary files/directories.
Deletion is not certified secure erasure. Abrupt process/power loss can leave
temporary files; inspect ownership and preserve useful recovery evidence before
any cleanup. No automatic broad cleanup or retention deletion is performed.

Publication uses a fully written, flushed stage and an atomic no-overwrite hard
link, followed by removal of the stage link. An output created by a concurrent
operation is not replaced. If publication succeeds but cleanup/directory flush
fails, the command may report failure although an output exists: inspect it,
never overwrite or automatically delete it. A crash between link creation and
stage unlink can leave two links; normal input/dispatch checks refuse that state.
Hardware durability and power-failure recovery still need target-host acceptance.

## Verification and remaining acceptance

Automated cases cover encrypted/randomized roundtrips, all existing table data,
record authentication, wrong keys, truncation/tampering, foreign databases,
schema drift, existing targets/sidecars, publication contention/failure, private
POSIX modes, WAL state with a concurrent uncommitted writer, sender exclusion,
restore-hold enforcement before publication and after restart, generic HTTP 503,
post-backup accepted jobs, reconciliation evidence and bounded CLI subprocesses.
All fixtures and provider results are synthetic. See [current platform
results](../deploy/README.md#local-and-linux-verification) for counts and skips.

Not yet verified: real-host disk-full/power-loss behavior, large-data performance,
off-host transfer, scheduled freshness/retention monitoring, operator/key recovery,
restoration of a real production archive, or safe promotion back to live use.
These remain release gates, alongside the wider product requirements.
