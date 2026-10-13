# Private setup and owner access

Autofever now has a local operator CLI for creating a new encryption key, a new
empty service database and an owner access code. It replaces the requirement to
write a Python script or edit SQL just to connect the owner interface.

It is **not public signup**, a password account, automatic hosting or a finished
device-recovery system. Only a trusted operator with access to the dedicated
database, its encryption key and private filesystem may run it. There is no HTTP
endpoint for provisioning. No setup command activates an illness episode, starts
a listener, contacts a provider or sends a notification.

## The three private artifacts

| Artifact | Purpose | Who may receive it |
| --- | --- | --- |
| Store key file | Decrypt the dedicated server database and its archives | Trusted server operator; separately protected key recovery |
| SQLite database | Episodes, queue, helper state, hashed access codes and encrypted records | Dedicated Autofever service/operator only |
| Owner credential file, conventionally `.afowner` | Persist an owner bearer capability and authenticated enrollment information | Trusted operator; transfer only the capability privately to that owner |

The owner capability grants control over that owner's episodes. Possession is
authority: no second password or login is added. Do not send the store key to an
owner or helper, and do not send owner capabilities to helpers. Helpers receive
their separate scoped links through the notification flow.

The `.afowner` file is private JSON, **not an encrypted vault**. Its `capability`
value is the access code to paste into the owner connection form. Its `mac`
authenticates the file but does not conceal it. Do not publish the file, put its
contents in a URL, paste it into a shared terminal/chat, or attach it to a support
issue. The CLI never prints the code, key or artifact contents.

The owner settings can create a different, encrypted `.afaccess` browser backup.
It contains only the owner's capability and helper-link duration, not profiles,
contacts, server history or pending local actions. Restore it only after opening
the intended Autofever server; check the displayed origin and explicitly confirm
before the browser makes read-only requests to validate the capability and save
it locally. Decrypting/checking the file alone makes no server request. This does
not revoke a lost device's access. The file and its strong passphrase should be
kept separately. For a lost or stolen device, a trusted operator still needs to
rotate the capability; the owner UI cannot perform that operation or verify
identity.

## Prerequisites and paths

- Use the configured backend Python environment from [backend setup](README.md).
- Run from the repository root against **only `028-autofever` state**, never
  Hire.ai's database, credentials or directories.
- Use private, existing parent directories on trusted local storage. New files
  request mode `0600`; temporary directories are private. Windows ACLs and parent
  directory ownership/permissions need operator verification. The CLI does not
  fix existing permissions or change file ownership for the runtime account.
- Use one canonical database path. Enrollment files are authenticated against
  that path and the store key. Moving a file does not rebind it to another store.
- Existing filenames and SQLite sidecars are refused for creation. There is no
  `--force`, overwrite, implicit key rotation or database replacement option.
- Keep credential/key artifacts outside the repository and served directories.
  `.afowner`, `.afkey` and owned staging directories are also ignored by Git;
  an arbitrary secret filename is not automatically protected by that rule.

## First-time setup

These are illustrative paths, not an already performed server installation.
`python` means the configured backend interpreter; on Windows this can be
`./backend/.venv/Scripts/python.exe`. Check each command's result before proceeding.

Create a store key **only for a new database**:

```sh
python -m backend.provision keygen --output /etc/028-autofever/store-key
```

For the separate hosted proxy secret, the same generator can be used with a
different new filename, for example `/etc/028-autofever/proxy-key`. Do not reuse
the store key as the proxy secret. No secrets are configured into services by
the generator itself.

Initialize a new empty database:

New stores use version 3, including update-message support. Existing version 1/2
stores are not automatically migrated by setup; use the explicit
[backup-first updates migration](updates.md#database-version-3-and-explicit-existing-store-migration).

```sh
python -m backend.provision init --database /var/lib/028-autofever/state.sqlite3 --key-file /etc/028-autofever/store-key
```

Create one owner and persist their access code:

```sh
python -m backend.provision owner --database /var/lib/028-autofever/state.sqlite3 --key-file /etc/028-autofever/store-key --credential-file /private/autofever-access/owner-001.afowner
```

Verify that same file against the registered owner:

```sh
python -m backend.provision check-owner --database /var/lib/028-autofever/state.sqlite3 --key-file /etc/028-autofever/store-key --credential-file /private/autofever-access/owner-001.afowner
```

Exit `0` confirms the specific local operation. Exit `2` means refusal/error and
prints a generic diagnostic. It does not print a traceback, personal database
records or credentials. The parser may report invalid command syntax, so never
put secrets themselves in command-line arguments.

`check-owner` verifies file authentication, the encrypted enrollment audit and
the owner's continued existence. It does not start the website, verify public
HTTPS, prove browser compatibility or test delivery.

## Connect the owner interface

After setting up the appropriate [local development listener](owner-api.md) or
the separately qualified [hosted transport](../deploy/README.md), open `/owner`.
Privately open the `.afowner` file with a trusted local text editor and copy only
its `capability` value into **Instellingen → Lokale server koppelen**. The form
checks the capability against the same-origin server before saving the connection.
Its current label still says “Lokale”; public hosting remains subject to the
deployment acceptance gates. Do not expose the development listener to achieve
remote access.

Secure transfer to a different device/person is still the operator's responsibility
and is not automated. Do not share the entire enrollment file or store key. A
successful local enrollment is not evidence that a physical phone has connected.

After connecting, the user prepares and saves contacts and the default profile.
Only their later **Ik ben ziek** action creates the episode/queue. Provisioning
does not make that choice for them and does not start the sender.

## Interrupted setup and explicit resume

The credential file is fully written, flushed and atomically published **before**
the SQL transaction commits owner creation. Its random capability cannot be
reconstructed from the hashes stored in the database. Therefore an interrupted
attempt preserves an existing credential file instead of deleting it.

If `owner` failed, was interrupted, or its successful result was lost:

1. Preserve the database and any credential file. Do not start again with a new
   filename merely to clear an error.
2. Inspect the existing file privately and check the exact database/key/path.
3. If the file exists, use the **same** command and file with `--resume`:

```sh
python -m backend.provision owner --database /var/lib/028-autofever/state.sqlite3 --key-file /etc/028-autofever/store-key --credential-file /private/autofever-access/owner-001.afowner --resume
```

Resume authenticates the file. It either completes the uncommitted enrollment
using that same code, or verifies the matching committed audit without inserting
another owner. Both owner insertion and its encrypted audit commit in one SQLite
transaction. SQLite can recover its own hot rollback journal after a process
crash; this is not a manual SQL repair. Do not remove journal/lock files yourself.

If the database records the enrollment but the owner is missing, resume refuses
instead of re-enabling access. An unknown, damaged, modified, oversized, duplicated-
field, wrong-path or wrong-key credential is refused. Missing files are not
silently regenerated. A second ordinary `owner` call with an existing filename
also refuses; resume is explicit.

If publication failed before any file exists, no owner is committed; after
checking that state, an ordinary fresh attempt may be appropriate. A filesystem
error can occur after a complete file has been published, so an error alone does
not prove that no output exists. Parent directories must be trusted; concurrent
replacement of paths and hostile local filesystem access are outside this model.

## What this does not recover or revoke

Creating an owner with a different new file creates a **different owner**, not a
replacement credential for an existing owner and not access to their history.
Deleting a credential file does **not** revoke the code. Owner capability
rotation/revocation is available through the separate [private access CLI](owner-access.md),
using the retained credential file and a coordinated software upgrade. Recovery
without that file, credential transfer, key rotation and a nontechnical
onboarding/recovery UI remain required work. `check-owner` also supports the
replacement file; an original enrollment replay cannot re-enable a revoked code.

Keep the original owner credential under separately protected recovery controls.
Server [backups](backups.md) retain only its encrypted enrollment audit and owner
hash, not the raw owner capability or file. An archive cannot reconstruct a lost
code. New archives with enrollment records require a backup verifier that knows
those records; older versions intentionally refuse unknown metadata.

Restored database copies remain under `restore-hold`. Setup, enrollment and
resume cannot bypass that block. Safe live restore promotion is separate work;
do not run an older release or remove the marker to make setup succeed.

## Verification boundary

Automated tests use disposable stores and synthetic identities. They cover
key/store creation, overwrite refusal, private POSIX modes, file tampering and
binding, wrong keys, missing/oversized files, resumability, concurrent attempts,
audit preservation in backups, restore-hold enforcement, secret-free CLI output,
actual subprocess death before commit and after the first SQL insert (with
synthetic cache pressure to force a genuinely hot rollback journal), and a real
loopback HTTP flow from provisioned credential to queued illness notification.
No provider is called. See [platform results](../deploy/README.md#local-and-linux-verification).

The procedure is not yet proven on the Hetzner host, with production identities,
physical phones, real operator/key recovery or real power loss. No Hire.ai state
or server configuration has been changed by these tests.
