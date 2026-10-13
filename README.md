# AutoFever

AutoFever is an illness-notification and practical-help application in development. Its purpose is to notify the people who need to know when sudden, temporary illness makes communication difficult, and tell them what they can do to help. Authorized absence-system integrations are a further intended capability, not a current connection.

The name is a wordplay: **auto** means automatic, and **fever** represents sudden temporary illness more broadly—not only a high temperature. This project has nothing to do with cars or RDW vehicle data.

The original idea is intentionally simple: configure the relevant recipients and practical help in advance, then use one prominent action when illness makes ordinary communication difficult. The completed service is intended to send an appropriate absence message, organize optional help, record actual delivery status, and later send a recovery notification. The current preview does not send messages.

> **Project status — 13 October 2026:** a runnable mobile preview is available in [illness-preview](illness-preview/README.md), alongside the incomplete historical Python prototype. Contacts can be imported from a reviewed local vCard file; import does not authorize a channel or select a recipient. Profiles, drafts, help preferences, encrypted backup/restore and accessibility settings also work locally. The optional local `/owner` mode connects that editor to the backend: one-press activation, real queue/help status, owner-only in-app check-ins, recovery and cancellation. A due check-in appears when the owner opens Autofever and is reset by an explicit confirmation; it does not message helpers or send a background notification. Owners can export encrypted server history, remove live server records, and separately clear this browser's local vault. Operator backups, previously delivered messages and automatic retention remain outside these controls. The separate `/help` page records recipient responses. Actual provider delivery, background reminders, recurring help and production hosting are not connected. This is not a production-ready notification service.

The current main branch also has a [GitHub Actions quality run](https://github.com/Robert-Velhorst/028-autofever/actions/runs/38433950051): 180 backend tests on Linux and eight mobile browser suites on Windows passed. CI exercises only synthetic/local flows; it neither deploys the service nor verifies a real provider.

An initial [SMTP email adapter and queue worker](backend/smtp.md) are also implemented: encrypted connections, private per-recipient messages, recovery messages and explicit handling of failed or uncertain submissions. They have been tested with temporary local mailservers only. There is no configured real mail account, public recipient site or external delivery proof. Running the preview does not start the worker or send messages.

For uncertain sends, a [private operator review tool](backend/reconciliation.md) can record a decision backed by verified provider evidence. It supports a non-mutating preview, an encrypted audit record and an explicit bounded retry only after confirmed non-acceptance. It refuses to settle a job while a sender is still active. It does not query providers or manufacture delivery proof; unresolved outcomes remain uncertain. This is not yet a complete nontechnical recovery flow.

[Hetzner deployment preparation](deploy/README.md) now includes a separate Waitress web entry point, authenticated HTTPS-proxy boundary, bounded request limits, private health checks and isolated service/proxy templates. Platform test results are recorded in the deployment guide. The Caddy example validates, but the actual shared host, public HTTPS flow, systemd service and production backup/restore have not been qualified. This does not mean Autofever is online.

[Server backup and recovery-copy tooling](backend/backups.md) creates encrypted, consistent archives, checks their integrity and restores them into a new, blocked review copy. Existing files are never overwritten. A restored copy cannot serve personal records or send messages: an older snapshot may contain notifications that were sent later, or links that were subsequently revoked. Safe live cutover, automated off-host backups, key recovery and retention still require further work; this is separate from the browser's profile export.

[Private owner setup](backend/provisioning.md) now provides local commands to generate a new key, initialize a new empty database, create owner access and check it. Access codes are written only to private files, not printed. Interrupted enrollment can resume with the same code without creating another owner. This removes the need for a custom setup script, but does not deploy the app, send messages or add public signup.

[Owner access management](backend/owner-access.md) lets a trusted operator replace a retained access credential without losing the account's episodes, or revoke that exact code. Old codes cannot regain access through setup replay. Interrupted replacement is resumable; messages and helper links are not cancelled by an access change. This requires the protected credential file and a coordinated upgrade to access-aware software; public lost-device recovery and a nontechnical recovery interface remain unfinished.

The [dependency security update](backend/dependency-security.md) replaces the vulnerable cryptography dependency, checks older encrypted test data and passes the backend suite on Windows and Linux. The audited runtime package versions have no currently reported vulnerabilities in that check. This is a bounded verification result, not a security certification or a claim that the product is complete.

[Tussentijdse updates](backend/updates.md) now connect the mobile owner interface to the encrypted server queue: write a short message, explicitly choose already-informed recipients, save a local draft or queue the update, and see its status. Lost responses can be retried without duplicate jobs. Personal helper pages show only the updates addressed to that person. Email submission is implemented and locally TLS-tested, but no production provider is configured. Existing databases require the documented backup-first v3 migration; new stores already support updates. Automatic reminders and recurring help are still unfinished.

The new [backend service and web interfaces](backend/README.md) implement persistent illness episodes, an encrypted outgoing queue, scoped recipient links and task responses. The local `/help` page lets a recipient explicitly acknowledge, accept, decline or complete assigned help without an account. The opt-in [owner connection](backend/owner-api.md) starts the saved profile rather than an unsaved draft and shows authoritative helper/queue status. Lost activation or recovery responses can be reconciled without starting a duplicate episode. This has automated service/HTTP tests and local Chromium interaction evidence with synthetic data; no real provider is connected. The historical Flask routes below are not this new service's API; its contract is in [OpenAPI](backend/openapi.yaml).

The owner page offers a passphrase-encrypted `.afexport` of server-side episodes and a separate action to remove the owner's live server records. A further control clears the local browser vault, including its owner connection. Local profiles, server history, downloaded backups, provider-delivered messages and operator-held backups have intentionally distinct boundaries; read the [owner API and deletion contract](backend/owner-api.md#http-contract). Automatic retention and expiry of off-host backups remain required work.

## Try the Mobile Preview

With Python 3 installed, run this from the repository root:

```sh
python -m http.server 8000 --bind 127.0.0.1 --directory illness-preview
```

Open `http://localhost:8000/`. No frontend build is required. Use a browser supporting IndexedDB and Web Crypto; localhost is supported, opening the HTML as a file is not. Keep the host and port stable to keep using the same browser storage. This loopback-only development server is not public or accessible from a separate phone.

The flow is: prepare a profile and contacts → save → press **Ik ben ziek** → inspect the local active snapshot → update, recover or cancel. **No recipient is contacted.** The UI explicitly shows that delivery and task acceptance have not occurred. Clearing site data can lose settings; use the password-encrypted backup first.

For developer checks, with Node.js/npm, PowerShell and Chromium available and the server running:

```powershell
./illness-preview/verify.ps1 -BaseUrl http://localhost:8000/
```

See [preview documentation](illness-preview/README.md) for limitations and [verification evidence](illness-preview/VERIFICATION.md) for the boundary between local tests and real delivery. No app account is required for this local preview.

## Why AutoFever Exists

Short-term illness often creates an immediate communication burden at exactly the moment when a person has the least energy and concentration available. Someone may need to contact a manager, colleagues, clients, teachers, classmates, caregivers, or family members, often through several different channels.

Existing messaging, calendar, and attendance tools can perform parts of this job, but generally require repeated manual actions. The result may be delayed messages, forgotten recipients, inconsistent wording, or uncertainty about whether the notification arrived.

AutoFever is intended to provide a calm, reliable communication layer for this specific situation. It is a communication utility, not a medical application, symptom checker, diagnostic service, or replacement for formal sick-leave procedures.

## Product Goals

- Reduce illness-related communication to the smallest safe number of actions.
- Let users configure recipients, groups, channels, and message templates in advance.
- Support both informal messages and formal absence-reporting integrations where authorized APIs exist.
- Work reliably with poor or temporarily unavailable connectivity.
- Make delivery, failure, acknowledgment, and queued status understandable.
- Provide a separate recovery flow when the user resumes normal activities.
- Protect health-related information through privacy-first defaults and explicit consent.
- Remain accessible to users with low energy, cognitive overload, motor limitations, or temporary impairment.

## Intended Users

AutoFever can support:

- employees who need to notify managers or teams;
- students who need to contact teachers, instructors, or project groups;
- freelancers who need to update clients and collaborators;
- parents or caregivers reporting an absence on behalf of a child or dependent;
- people balancing several roles who must notify different groups;
- organizations that choose to integrate AutoFever with an authorized attendance workflow.

## Core User Experience

### 1. One-time setup

The onboarding flow should help the user:

1. create or import relevant contacts;
2. place contacts into purpose-specific groups;
3. configure permitted delivery channels;
4. select or edit an absence template for each group;
5. configure a recovery template;
6. connect supported school, work, calendar, or attendance systems;
7. review privacy and consent settings;
8. send a harmless test notification.

Importing a contact must never automatically authorize the disclosure of illness information. Recipient selection and channel authorization require explicit confirmation.

### 2. Activate illness mode

The primary interface contains one prominent illness action. Activating it should:

1. use the saved default profile, not unsaved drafts;
2. snapshot the configured recipients, messages and practical help;
3. activate immediately with that single deliberate action, without a second confirmation or last-minute questionnaire;
4. send through configured, authorized channels once the delivery backend exists;
5. display actual delivery and failure status without demanding further work from the user;
6. start an illness episode for later updates, help coordination and recovery.

Recipient/disclosure review and optional duration or message editing belong in preparation, before saving. This one-press rule follows the owner's explicit product decision. The standalone preview stops at a local snapshot. The optional local owner connection creates an actual server episode and outgoing queue, but no external provider is connected. Unknown request outcomes retain the original command for reconciliation; this is not an automatic offline delivery service.

The default message should disclose no more than necessary. A neutral formulation such as “I am unavailable today for health reasons” should be available for users who do not want to state that they have a fever or another illness.

### 3. Recovery and return

When illness mode is active, the user can send a recovery or return notification. This flow should:

- reuse the recipients from the active illness episode;
- permit recipient or message changes before sending;
- notify connected systems that the absence has ended where supported;
- close the illness episode;
- retain a local audit record according to the user's retention settings.

AutoFever may remind the user to review an active episode, but it must never announce recovery automatically without explicit authorization.

## Functional Scope

### Contact and group management

- manual contact creation;
- optional address-book import;
- separate work, education, family, client, caregiver, and custom groups;
- per-recipient delivery channel;
- duplicate detection;
- temporary inclusion or exclusion;
- clear disclosure preview for every recipient.

### Message templates

- group-specific absence templates;
- neutral and privacy-preserving defaults;
- optional expected-duration and return-date fields;
- recovery templates;
- message preview and editing;
- localization and tone preferences;
- no fabricated medical detail.

### Notification delivery

Potential adapters include email, SMS, device messaging intents, workplace platforms, calendars, and authorized attendance systems. Every adapter must report a normalized delivery state:

- `draft`;
- `awaiting_confirmation`;
- `queued_offline`;
- `sending`;
- `sent`;
- `delivered` where the provider supports proof;
- `acknowledged` where the recipient explicitly responds;
- `failed`;
- `cancelled`.

A provider accepting a message is not the same as confirmed delivery, and delivery is not the same as recipient acknowledgment.

### Offline and low-bandwidth support

- locally cached contacts, templates, and settings;
- durable encrypted notification queue;
- automatic retry with bounded backoff;
- visible sync status;
- duplicate-send prevention;
- low-bandwidth mode;
- conflict-safe state recovery after restart.

### Accessibility

- large, high-contrast primary controls;
- screen-reader labels;
- keyboard navigation;
- reduced-motion support;
- voice activation as an optional accessibility feature;
- confirmation that is accessible without relying on color alone;
- plain-language status and error messages.

Voice activation is planned, not implemented. It must activate only previously authorized saved settings; its accidental-activation safeguards still need design and verification. Do not silently add a second confirmation to the agreed one-button manual flow.

### Feedback and acknowledgment

The prototype anticipates optional recipient acknowledgment links. These must use short-lived, unguessable, single-purpose tokens and reveal the minimum possible information. Acknowledgments are optional and cannot be treated as proof that an employer, school, or other institution formally accepted an absence.

## Privacy, Security, and Safety

Illness information can be health data and therefore requires particularly careful treatment. A production implementation must include:

- data minimization and purpose limitation;
- device-first processing where practical;
- encryption at rest and in transit;
- explicit authorization for recipients, channels, and integrations;
- a disclosure preview when configuring the saved plan, before activation;
- configurable local retention and complete deletion;
- no advertising use or sale of health, contact, or communication data;
- no continuous health surveillance;
- no automatic diagnosis or health inference;
- no silent addition of recipients suggested by AI;
- revocable integration tokens;
- auditable notification events without unnecessary message-body retention;
- protection against replay, duplicate delivery, and unauthorized acknowledgments;
- GDPR-compatible access, export, correction, and deletion workflows where applicable.

Emergency situations are outside the primary scope. AutoFever must not imply that it contacts emergency services or substitutes for medical assistance.

## Target Architecture

A production implementation should separate the following components:

### Client application

- onboarding and configuration;
- one-action illness and recovery interface;
- encrypted local storage;
- offline queue;
- accessibility and localization;
- recipient and disclosure confirmation.

### Policy and orchestration layer

- recipient resolution;
- template rendering;
- consent enforcement;
- illness-episode state machine;
- idempotency and duplicate prevention;
- retry policy;
- normalized delivery status.

### Delivery adapters

- email;
- SMS;
- supported messaging platforms;
- calendar status;
- workplace or education systems with official integration support.

Adapters must use documented APIs or user-controlled device actions. AutoFever must not depend on credential scraping, fragile browser automation, or unauthorized access to institutional systems.

Current implementation: [SMTP email](backend/smtp.md) uses the existing encrypted backend queue, requires explicit configuration and an approved recipient list, and submits only when the worker is started with `--send`. The non-sending `--check` validates local settings only. Other channel adapters, provider callbacks and production delivery verification remain open. A mailserver accepting an email is not proof that it reached an inbox or was read.

### Optional backend

A backend is only required for functions that cannot safely remain on-device, such as provider callbacks, cross-device synchronization, or organization-managed integrations. It should not become a central store of contact lists and health messages by default.

## Conceptual Data Model

### UserProfile

- locale and timezone;
- accessibility preferences;
- privacy and retention settings;
- configured channel adapters.

### Contact

- stable local identifier;
- display name;
- role;
- authorized destinations;
- group membership;
- disclosure preference.

### ContactGroup

- name and purpose;
- members;
- default template;
- enabled channels.

### MessageTemplate

- audience and locale;
- content;
- supported variables;
- sensitivity classification;
- last user confirmation.

### IllnessEpisode

- start time;
- optional expected duration or return date;
- state: `draft`, `active`, `recovering`, or `closed`;
- recipient snapshot;
- associated notification events.

### NotificationEvent

- idempotency key;
- episode, recipient, and adapter;
- rendered disclosure level;
- timestamps;
- delivery state;
- retry and failure information;
- acknowledgment state.

## Prototype API Surface

The current Python prototype sketches the following Flask routes:

- `GET /api/state`;
- `POST /api/activate-illness`;
- `POST /api/activate-recovery`;
- `GET /api/contacts`;
- `GET /api/templates`;
- `GET|POST /api/settings`;
- `GET /api/statistics`;
- `GET /api/resource-usage`;
- `GET /api/optimize-resources`;
- `GET /acknowledge/<token>`;
- `POST /api/acknowledge`;
- `POST /api/voice-command`;
- `GET /api/sync-status`.

These routes document prototype intent only. They are not a stable or secured public API.

## Repository structure and supported paths

The maintained implementation is split into a static, mobile-first browser app and an optional Python service. They deliberately have different data and delivery capabilities:

- `illness-preview/` contains the profile editor, local encrypted vault, encrypted export/import, contact review, and the standalone local-only flow. See its [user-facing guide](illness-preview/README.md) and [browser verification record](illness-preview/VERIFICATION.md).
- `backend/` contains the persistent service, SQLite data model and migrations, versioned HTTP API, owner and recipient interfaces, protected help responses, encrypted queue, SMTP adapter/worker, private provisioning and access tools, backup/restore, and owner data controls. See [backend documentation](backend/README.md), [OpenAPI contract](backend/openapi.yaml), and [privacy and security boundaries](backend/owner-api.md).
- `deploy/` contains isolated web/worker service templates and reverse-proxy guidance for a future separate `028-autofever` deployment on the existing `013-hire-ai` server. It is preparation, not a live installation. The guide records exact acceptance gates and [current verification](deploy/README.md).
- `app_enhanced_optimized_fixed.py`, `code_review_findings.md`, and `code_fixes_report.md` are historical prototype/review artifacts. The Python file imports modules absent from this repository; it is not the maintained service and its old claims are not current test evidence.

The standalone browser app does not send notifications. The optional owner connection uses the backend for persistent episodes and status. Email sending is implemented and tested against local synthetic SMTP servers, but no real provider/account is configured. Check-ins are owner-only and appear in Autofever when opened or refreshed; no helper or background notification is generated. Configured recurrence and backup helpers are not automated. These distinctions are intentional and also described in the detailed component guides.

## Running and verifying

For the browser-only preview, start Python's static server from the repository root and bind it to loopback:

```powershell
python -m http.server 8000 --bind 127.0.0.1 --directory illness-preview
```

Open `http://localhost:8000/`. To run its eight isolated Chromium suites, Node.js/npm and Chromium are needed:

```powershell
./illness-preview/verify.ps1 -BaseUrl http://localhost:8000/
```

For the service, use Python 3.11+, create an isolated virtual environment and install `backend/requirements.txt`; then run the commands in [backend test instructions](backend/README.md#run-the-tests). The documented test suite uses synthetic data and local-only services. The hosted entry point refuses implicit serving and exposes only a loopback listener behind its configured proxy. See [deployment preparation](deploy/README.md) before attempting any hosted setup.

The current GitHub Actions workflow has passed 180 backend tests on Linux and all eight browser suites on Windows for the documented checkpoint. This validates local/synthetic behavior only. It is not evidence of production deployment, public HTTPS, provider delivery or physical-device acceptance.

## Release readiness and remaining work

The private owner/helper workflows, explicit recovery and cancellation, idempotent queue operations, local SMTP transport, owner check-ins, encrypted exports, live-record deletion and browser-vault clearing are implemented and covered by automated/local verification as detailed above. They do **not** make the service ready for public users.

The remaining release gates include: authenticated read-only inventory of the existing `013-hire-ai` host; a dedicated domain and approved routing; qualification of the current release and service isolation on that host; verified backup and recovery operations; physical-phone and public HTTPS acceptance; approved real email provider/sender configuration and a controlled delivery test; nontechnical owner credential recovery/onboarding; off-host backup scheduling and key-recovery procedures; and a fresh isolated-container verification for the current commit. No Hire.ai database, key, service, proxy configuration or firewall is to be repurposed for Autofever.

Formal workplace, school, calendar or attendance integrations are future capabilities only. They require a real authorized integration path and must not be simulated. The app does not diagnose illness, infer health state, recommend treatment, decide work/school fitness or guarantee formal acceptance of an absence.

## Non-Goals

AutoFever is not intended to:

- diagnose illness or recommend treatment;
- decide whether a person is fit for work or school;
- infer health status without explicit input;
- automatically disclose illness to suggested contacts;
- impersonate the user in protected institutional systems;
- guarantee that an absence is formally accepted;
- replace emergency services, medical care, or organizational sick-leave policy.

## Success Criterion

AutoFever succeeds when a person who is temporarily unwell can responsibly notify everyone who genuinely needs to know—with the minimum safe effort, no forgotten recipients, clear delivery status, and full control over the health information being disclosed.
