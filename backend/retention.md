# Optional server-history retention

An owner can set an optional retention period in **Settings → Automatic retention**. The default is off. A period is an integer number of days from episode closure (1–3650); leaving the field empty disables the policy. The closure time is stored encrypted with the episode. The encrypted server database backup preserves the setting; the separate owner history export contains episodes, not configuration.

On the server, the daily `028-autofever-retention.timer` runs the bounded cleanup CLI. It processes up to 100 episodes per run; later runs continue if there is a backlog. No data is deleted until an owner has explicitly set a period **and** the operator has enabled the timer. When delivery/reconciliation owns the shared lock, the run exits without deleting anything and the next scheduled run retries.

Only episodes already closed as recovered or cancelled for at least the chosen period are eligible. Active episodes are never eligible. An episode is also retained while any queued, sending or uncertain job remains; it must not discard a message that has not been sent or erase an ambiguous provider outcome. Accepted, failed and cancelled jobs can be removed with an otherwise eligible closed episode. The live episode, contact snapshots, recipient capabilities and responses, tasks, check-ins, updates, delivery records, closure timestamp and reconciliation metadata are removed together in one SQLite transaction. The owner credential and retention setting remain, so Autofever can still be used for a new episode. Pre-existing closed episodes from before closure timestamps were recorded are retained automatically because their exact closure age cannot be established; a user may remove them with the explicit server-history deletion control.

Saving a shorter period prompts for confirmation because the next cleanup can remove older, closed live history immediately. The setting does not erase sent messages, copies already held by recipients, local browser profiles, downloaded exports, operator backups or off-host backups. SQLite row deletion is logical application deletion, not guaranteed physical overwrite of storage, WAL files or filesystem snapshots. Backup expiry, key recovery and restoration policy are separate operator responsibilities.

## Operator commands

Validate the existing dedicated store and private store-key credential without deleting data or contacting a provider:

```sh
python -m backend.retention --database /var/lib/028-autofever/state.sqlite3 --key-file /run/credentials/store-key --check
```

The systemd template uses the following destructive mode only after the operator enables the timer:

```sh
python -m backend.retention --database /var/lib/028-autofever/state.sqlite3 --key-file /run/credentials/store-key --purge --limit 100
```

The cleanup uses the same inter-process delivery lock as dispatch and reconciliation, emits only the number of removed episodes, and has no network access. A skipped busy run is nonzero and leaves all rows unchanged. Keep the timer and service isolated to the dedicated `028-autofever` store; never point them at Hire.ai data.

The unit pair in `deploy/028-autofever-retention.service` and `deploy/028-autofever-retention.timer` is a reviewable template, not installed or qualified on the Hetzner host. Review paths, systemd support, file permissions, schedule and logs before enabling it.
