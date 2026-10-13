# Reviewing uncertain sends

Autofever provides a **private operator CLI**, not a public API, for settling one uncertain send attempt using verified provider evidence. It never contacts a provider itself and cannot establish whether an operator's assertion is true. No real decision has been applied by the development tests; their records and evidence references are synthetic.

Use this when the sender lost the decisive reply or a worker crashed. A normal user cannot overwrite delivery state through their owner or recipient capability. The administrator needs filesystem access and the separate database encryption key. This is an operational recovery tool, not the completed user-facing uncertainty experience.

## Evidence and permitted decisions

Before making a decision, stop the relevant workers and verify the actual provider's record for the **exact job and attempt**. Match the submission, sender, intended recipient and timing privately. A stable Message-ID alone does not prove which attempt was accepted, rejected or delivered. Retain the external evidence in the operator's protected system and record its reference, not a message body, diagnosis, password or personal action link.

| Authoritative observation | Decision | Effect |
| --- | --- | --- |
| Provider record/support confirms acceptance | `accepted`, `retry: false` | Mark accepted; no resend; enables ordinary recovery targeting |
| Provider confirms definite non-acceptance; no new attempt wanted | `not_accepted`, `retry: false` | Mark failed; no resend; allows episode closure |
| Provider confirms definite non-acceptance; explicit retry authorized | `not_accepted`, `retry: true` | Queue the same job after 30 seconds, subject to expiry and attempt limits |
| Outcome unknown; record absent/incomplete; recipient cannot find the email | No decision | Keep uncertain; no automatic retry or invented success |

Acceptance still does not prove inbox delivery or reading. A later bounce is not evidence that the original SMTP submission was never accepted. Do not use `not_accepted` for that case. Recipient acknowledgments remain separate. The CLI does not authenticate an operator name against an identity provider or verify an evidence URL; those are trusted operator assertions.

## Inspect first

From the repository root, with the existing `AUTOFEVER_STORE_KEY_HEX` supplied privately:

```powershell
./backend/.venv/Scripts/python.exe -m backend.reconcile --database C:/private/autofever/state.sqlite3 --job JOB_UUID
```

Paths and IDs in these examples are placeholders, not provisioned production files. On Linux use `backend/.venv/bin/python`. The database must already exist and match its key; the CLI does not provision a store or owner. It does not load `.env` files.

The report contains job/episode identifiers, kind, state, attempt number, due/lease timestamps and redacted resolution summaries. It omits message bodies, contact identities, addresses, capabilities, sender receipts and operator/evidence text. Keep even this metadata private. Read-only review does not expire a lease, consume a queued job or apply a decision.

## Prepare and preview a decision

Create a private JSON file **outside the repository**, restricted to the operator. Exact fields are required; duplicate/unknown fields are rejected. Example shape only:

```json
{
  "job_id": "REPLACE_WITH_EXACT_JOB_UUID",
  "attempt": 1,
  "outcome": "accepted",
  "retry": false,
  "operator": "REPLACE_WITH_OPERATOR_ID",
  "evidence_source": "provider_record",
  "evidence_reference": "REPLACE_WITH_VERIFIED_PRIVATE_RECORD_REFERENCE"
}
```

`evidence_source` must be `provider_record` or `provider_support`. Fill every value from actual review; the application cannot detect invented references. Merely copying this example is not evidence. The file has a 16 KiB limit and must not be a symlink. Protect its directory and permissions; the CLI does not secure existing ACLs or provide automatic evidence-file retention/deletion.

Preview without applying:

```powershell
./backend/.venv/Scripts/python.exe -m backend.reconcile --database C:/private/autofever/state.sqlite3 --decision C:/private/autofever/decision.json
```

The result reports the proposed queue status with `applied: false`. No network call or job change occurs. A preview is not a reservation: application rechecks the lock, attempt, job, link expiry and episode state.

Only after verifying the evidence and retry choice, persist it explicitly:

```powershell
./backend/.venv/Scripts/python.exe -m backend.reconcile --database C:/private/autofever/state.sqlite3 --decision C:/private/autofever/decision.json --apply
```

Applying never directly sends anything. However, an explicit retry makes the job eligible for a configured worker after 30 seconds. Recheck the preview/result and recipient authorization before restarting workers. Retrying retains the same job ID, payload and personal link; it cannot change recipients, extend an expired link, reset the attempt counter or exceed five attempts. Accepted jobs cannot be retried. Failed/queued/cancelled jobs cannot be overwritten with this interface; retrying an independently failed job remains separate required work.

Exit 0 means review/application completed, not delivery. Exit 2 means invalid input/access/configuration; exit 3 means active delivery or a conflicting state/decision; exit 1 means another failure. Error output does not expose evidence or secrets. After an unknown application result, repeat the **identical** decision: it returns the recorded result without applying again. A replay can describe an earlier `queued` result even if a worker has since progressed; use `--job` for the current state. Changing any decision/evidence field for the same attempt is refused.

## Concurrency, durability and boundaries

- A same-host OS lock beside the canonical database (`state.sqlite3.dispatch.lock`) is held across dispatch, including the network call and persisted outcome. Reconciliation requires the same exclusive lock immediately; ordinary dispatch waits up to ten seconds. A competing SMTP worker does not claim a job while the lock is busy. This initial implementation serializes provider submissions for a store.
- The lock file's existence is **not proof of a running process**. OS lock ownership matters. Process exit releases ownership; the sidecar remains intentionally. Do not delete or replace it to bypass an active lock. A five-minute lease can expire while a sender is still alive; quarantine alone therefore does not authorize reconciliation.
- A crashed `sending` attempt can be reconciled only after its lease expires and the OS lock is free. An explicit `uncertain` outcome can be reviewed when no sender holds the lock. No automatic action equates a crash, timeout or missing receipt with non-acceptance.
- All worker and operator processes must use this code and the same dedicated canonical database on **local storage**. Stop old-version workers before upgrading. Do not run old code concurrently, use hardlinked databases, swap the sidecar/database under running processes, or put this SQLite/lock arrangement on shared/network storage. Host filesystem permissions remain part of the trust boundary; this does not defend against another administrator.
- Decision, operator ID, evidence reference, timestamp and resulting status are encrypted using the existing authenticated-record format and stored under `resolution:<job-id>:<attempt>` in `metadata`. Inserting the record and changing the job are one SQLite transaction. No schema migration or change to the key-check is required. Records are append-only through this interface, not tamper-proof against a key-holding operator or rollback to an old backup.
- The owner sees the resulting ordinary queue status on refresh; recipient responses are unaffected. The detailed audit is operator-only and is not added to HTTP responses. The trusted `Store.open` method can decrypt the record for a controlled local audit; the CLI deliberately prints only summaries. A structured audit export and retention policy remain production work.

Lock primitives: [Python Windows byte-range locks](https://docs.python.org/3.11/library/msvcrt.html#msvcrt.locking) and [Python Unix file locks](https://docs.python.org/3.11/library/fcntl.html#fcntl.flock). Windows behavior is exercised locally, including separate-process contention and actual process death. The POSIX implementation still requires Linux verification before Hetzner deployment.

## Verification and remaining work

Automated tests cover dry-run preservation; encrypted durable audit; idempotent replay after restart and after a later attempt; refusal of altered/stale/unsupported decisions; explicit bounded retry; expired links and exhausted attempts; transaction rollback; recovery targeting and new-episode ordering; live-sender exclusion after lease quarantine; process death; concurrent decisions; CLI privacy and missing-database refusal; worker contention. They use disposable databases, injected senders and synthetic provider assertions, not live provider records.

Unresolvable outcomes deliberately remain uncertain. A complete nontechnical user path for that case, provider-specific evidence retrieval, verified external delivery/bounce events, failed-job recovery, audit export/retention, Linux acceptance and production operations are still required. No production database, provider account, server configuration or real contact was used for these tests.
