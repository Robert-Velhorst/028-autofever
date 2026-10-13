# Autofever — illness coordination mobile preview

Autofever means automatic communication when sudden temporary illness makes it difficult to notify people yourself. Set up contacts, messages and practical help while well; one button activates the saved default plan. It is not automotive software, medical advice, diagnosis or an emergency service.

## Current status

This directory contains the functioning **local-only mobile preview**, integrated as source files onto the clean repository history in October 2026. The incomplete Python prototype in the repository root is separate. No rejected automotive code or old Git history is included in this integration.

The preview does not send messages, create reminder jobs, contact backup helpers or receive recipient acknowledgements. Selecting a channel or a recurrence is configuration, not an integration. Activating a plan prepares a local snapshot; the screen explicitly distinguishes it from actual delivery or acceptance of a task.

### Implemented

- Mobile layout with four collapsible profile sections: message, people, help and follow-up.
- Contacts and profiles can be created, edited and removed. Optional individual messages show a preview of the effective message before saving.
- Contacts can be imported from a local `.vcf` vCard file. The app previews names and available address choices, excludes detected duplicates, and requires an explicit import action. Importing does not select delivery channels or add contacts to any illness profile; both require later user choices. The file is parsed in the browser and is not uploaded by the import flow.
- Profile, contact and update drafts are automatically stored separately from published settings. Navigation and reload preserve drafts; publishing or explicitly discarding a draft clears it.
- The home screen shows recipient count and missing contact/task details. Email requires an email address; SMS and WhatsApp require a plausible phone number when a contact is saved. These are format checks, not proof that a destination exists or belongs to the person.
- Help tasks record instructions, intended helpers, a timing description, once/daily/weekly preference and an optional backup person. Recurrence and backup contact are not executed.
- Activation snapshots the saved plan. Later profile edits do not change that active snapshot. Updates can be kept locally; recovery and cancellation close the local preview.
- AES-GCM encrypted browser storage, including separate encrypted drafts. Optimistic revision checks reject stale saved-data writes from another tab. Different draft records are merged when saved. Simultaneously editing the same draft remains a last-writer case; do not claim collaborative editing support.
- Downloadable, password-encrypted backup and restore covering contacts, profiles, active preview and drafts. Backup format v1 uses PBKDF2-SHA256 (600,000 iterations, random 16-byte salt) and AES-GCM (random 12-byte IV). Import checks the envelope, authenticates ciphertext, validates its contents and requires confirmation before replacement. Files larger than 5 MB are rejected.
- Settings provides a separately confirmed control to clear this browser's local vault, including profiles, contacts, drafts, and the optional server connection. Other tabs are notified and reload; stale writes are rejected. This does not delete server records, downloaded backups, or previously delivered copies.
- Accessible labels, page-heading focus on navigation, focus on newly added tasks, invalid-field section expansion and a separate save area below the scrolling editor. Save controls do not float over the form.
- Optional larger text and high-contrast presentation under Settings. Preferences persist locally and travel with encrypted backups; older backups without preferences continue to work.

## Run locally

No frontend build or package installation is needed. From the repository root, with Python 3 installed:

```sh
python -m http.server 8000 --bind 127.0.0.1
```

Open `http://localhost:8000/illness-preview/`. Stop the development server with Ctrl+C. The repository-root server exposes only loopback on this command and lets the verifier exercise both the preview and isolated helper page. This is not a phone-accessible production deployment. Production hosting must provide HTTPS, appropriate security headers and a stable origin.

Web Crypto and IndexedDB require a supported browser and a secure context (HTTPS or localhost). Use a stable host and port: changing the origin means different browser storage. Opening the HTML directly from the filesystem is not the supported route.

## Data and privacy boundaries

The storage encryption key is in the same browser database as the ciphertext. Encryption does **not** protect data from someone using the unlocked browser or malicious scripts running on the same origin. No account, mandatory app PIN or biometrics are introduced.

Backups use an independent user-supplied passphrase. The app does not retain that passphrase; a lost passphrase cannot be recovered. Keep the backup file and passphrase separately. Clearing browser/site data can destroy local settings without a backup. Restoring replaces this browser's data and does not send notifications.

The local-vault deletion control removes the current browser's saved records and connection; it does not erase server history, downloaded backup files, operator-held backups, or messages/copies already delivered to other people. This is a local browser-storage action, not a remote account or backup-erasure request.

Sample contact names illustrate configuration; blank sample contact details are deliberately reported as incomplete. Do not mistake these samples for imported contacts.

## Verification and remaining work

With the development server running, Node.js/npm installed and Chromium available, run this from the repository root in PowerShell:

```powershell
./illness-preview/verify.ps1 -BaseUrl http://localhost:8000/illness-preview/
```

The runner uses a pinned Playwright CLI version, creates a dedicated browser session, runs eight preview suites in isolated contexts with synthetic data, then tests the bilingual recipient interface from the repository-root server before closing its session. The first invocation may download the test runner from npm. It accepts loopback URLs only. Tests do not import your browser profile, contact external recipients or need a preview-session key. Test definitions are in `tests/`; paths are relative to the script, not to the original author's computer. Generated CLI artifacts are ignored by Git. The deletion suite checks that a stale tab cannot restore records after the local vault is cleared.

Before opening a browser, the runner checks its result-handling contract. A missing result, duplicate success results, a reported tool error or a failed process must fail the run; exit code zero by itself is not treated as proof that a browser test passed. Each browser suite must return exactly one explicit successful result. These controller checks can also be run separately with `./illness-preview/tests/runner-contract.ps1`.

See `VERIFICATION.md` for the tested behavior and the remaining end-to-end gates. This preview is not the completed Autofever product. Live delivery, private recipient action links, reliable reminders/escalation, task acceptance/completion, production HTTPS deployment and provider acceptance remain to be built and verified. Source integration does not satisfy those requirements; do not merge the old automotive branch or restore the old repository history.
