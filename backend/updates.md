# Tussentijdse updates / episode updates

While an illness episode is active, its owner can write a short update and choose
which already-informed people should receive it. This connects the mobile
`/owner` interface, authenticated API, encrypted queue, SMTP adapter and personal
`/help` view. The standalone browser preview remains local-only.

There is still no configured production mail account or hosted public service.
A queued update is **not** proof of sending, delivery or reading. Tests use
synthetic identities and local test infrastructure, never real contacts.

## Mobile flow

1. Open the active server episode and choose **Update schrijven**.
2. Enter up to 2000 characters and explicitly select recipients. Nobody is
   selected by default. Only people whose initial illness message was accepted
   by the sender can be selected; acceptance still does not prove delivery.
3. **Concept bewaren** encrypts the draft in this browser's connection record.
   It survives reload but is not sent, synchronized to another device or included
   in the profile export. Unsaved editing remains in memory only.
4. **Update in wachtrij zetten** durably saves the exact pending command locally
   before sending the request. The server creates one separate job per selected
   recipient, and the owner sees the update history and per-recipient status.
5. After an unknown outcome, use **Uitkomst controleren**. The same command is
   retried; reload also reconciles an already-recorded update against the exact
   message and selection. A new command is not generated merely because an
   answer was lost. Do not clear browser storage to resolve uncertainty.

A saved draft is separate from the frozen pending request. A definitively
rejected request leaves the draft available; an unconfirmed result keeps its
pending command. Multiple-tab connection writes use the existing revision check.
Account switching stays blocked while a prior command is unresolved.

## Scope and ordering

- The owner can choose only recipients from the same episode whose original
  `illness` job is `accepted`. Queued, failed or uncertain initial sends are not
  silently treated as informed. No contacts are added automatically.
- A message and sorted selection are frozen under `(episode_id, command)`.
  Repeating identical content is safe, including after closure. Reusing that
  command with different content returns a conflict. Selection order alone
  does not change identity.
- At most 50 updates are recorded per episode. A new update is refused while a
  previous update has queued, sending or uncertain jobs, preserving ordering.
  Already failed jobs are not automatically retried; their statuses stay visible.
- Updates contain text only, no new recipient capability. They do not extend
  helper-link lifetime, change the saved profile/tasks, acknowledge reading or
  count as recovery. Scheduled check-ins and automatic reminders remain absent.
- The original personal helper page shows only updates addressed to that
  recipient, even before email submission finishes. This is server availability,
  not email-delivery evidence. The reading button acknowledges the original
  illness message only; updates have no independent read receipts yet.
- Recovery/cancellation cancels still-queued illness and update jobs. A sending
  or uncertain job must first be resolved. Recovery messages still go only to
  recipients whose initial illness notification was accepted.
- An uncertain update uses the existing private reconciliation procedure.
  Explicit retry after verified non-acceptance requires the episode still to be
  active. The service never guesses provider outcomes or recalls accepted mail.

Opening another personal link in the same tab now clears the previous content
and reads the new capability. A generation check ignores late responses from
the previous link. Tokens are removed from the visible URL and kept in memory;
an existing page/device or an already-sent message cannot be remotely erased.

## API

`POST /api/v1/owner/episode-updates` uses the existing same-origin owner bearer
boundary and hosted request quotas. It accepts exactly:

```json
{
  "episode_id": "the-owned-episode-id",
  "command": "a-new-unique-command-id",
  "message": "Ik neem morgen ook rust.",
  "recipients": ["chosen-contact-id"]
}
```

The command is 1–128 ASCII letters/digits/underscore/hyphen. The message must be
nonblank, at most 2000 characters and contain no NUL. Choose 1–100 unique valid
recipient IDs. Body limit: 32768 bytes. Success is `200 {data: <owner view>}`,
matching the existing idempotent owner-command API. Invalid bodies are `400`,
unavailable ownership `404`, conflicting state/selection/command or an unmigrated
store `409`. Other transport failures follow [OpenAPI](openapi.yaml).

Owner views add `updates` with command, message, chosen IDs and creation time;
notification kind can be `update`. Recipient views add only that recipient's
update message/time, never another person's identity or selection. Rendering
uses text/escaping, not user-supplied HTML. Original episode snapshots remain
unchanged. Update records and delivery envelopes are encrypted at rest.

## Database version 3 and explicit existing-store migration

New dedicated stores now start at database version **3**. Existing version 1/2
stores still open without automatic schema changes and can run their existing
lifecycle, but cannot accept updates until explicitly migrated.

Version 3 adds `jobs.batch`, permits `kind='update'` and replaces uniqueness with
`(episode, recipient, kind, batch)`. Existing illness/recovery jobs retain an
empty batch. An encrypted `update:<episode>:<command>` metadata record binds the
message and selection. Backup verification checks these records against episode
recipients, queue jobs and decrypted update envelopes. Archive encryption format
is unchanged; older verifiers/runtime releases do not support v3.

For an existing store:

1. Stop **all Autofever processes** on the dedicated database, including workers
   and listeners. Do not stop or change Hire.ai. Preserve the canonical paths and
   separately protected keys. This is an offline migration, not zero-downtime.
2. Choose a new private archive filename; the migration requires a successful
   encrypted backup before changing tables. Existing files are never replaced.
3. Run from the repository root with the configured backend interpreter:

```sh
python -m backend.migrate_updates --database /var/lib/028-autofever/state.sqlite3 --key-file /etc/028-autofever/store-key --backup-output /private/autofever-backups/before-updates.afbackup
```

4. Check exit status (`0` success/already-v3, `2` failure) and keep the backup.
   Restart only v3-aware Autofever code and reload browser clients. Validate
   operator access, helper isolation, queue status and host health before release.

These are illustrative paths, not an operation performed on Hetzner. The CLI
validates the exact legacy schema, excludes active dispatch using its OS lock
and refuses persisted `sending` jobs. It copies the jobs table within one SQL
transaction, verifies all original job values survived, checks the target schema
and relationships, then commits version 3. Other tables, owner access records,
IDs, encrypted payloads, receipts, attempts, due times and statuses are retained.
No job is reset or submitted. A SQL failure rolls the schema change back.

After interruption, preserve every file and inspect the database version and
backup privately. A fresh retry needs a new backup filename; a v3 source creates
a new backup and reports no migration needed. Do not lower the version, restore
old state over live state, remove journals/locks, or run old code as a workaround.
Fix forward; old snapshots can revive sent messages and revoked access. Restore
copies stay under the existing quarantine. Key rotation/live restore promotion
and production-scale migration acceptance are separate work.

## Verification boundary

Service/HTTP tests cover authorization, explicit accepted-recipient selection,
immutable snapshots, input/limit handling, concurrent idempotency, interrupted
batch rollback, closure, uncertainty, encrypted backup bindings and v1/v2
migration preservation/refusal/rollback. SMTP tests include actual local TLS
transport of a queued update, its private recipient and absence of a new link.

Local Chrome/Playwright exercised the real owner/helper HTTP service at 320, 390
and 1280 CSS pixels: encrypted draft reload, selected recipients, two deliberately
lost JSON replies after the real mutation committed, identical-command retry,
reload reconciliation with exactly one update job, escaped user text and helper
isolation. A delayed real HTTP response was released after switching helper links
to verify stale-response suppression. Page identity, populated content, no error
overlay, console health, screenshots and no external browser requests passed.
This used the bundled Node runtime after the system Node/npm CLI failed on exit;
the specific Browser skill was unavailable. No provider delivery was simulated
as real acceptance: the UI fixture's sender was explicitly synthetic.

See [platform results](../deploy/README.md#local-and-linux-verification). Physical
phones, Safari, assistive-technology acceptance, live provider delivery and the
shared Hetzner host remain unverified. These updates do not complete reminders,
recurring tasks, escalation, reserve helpers or fallback channels.
