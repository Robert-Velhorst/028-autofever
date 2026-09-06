# AutoFever

AutoFever is a low-friction illness-notification application. It allows a user to notify predefined people and connected absence systems when they are temporarily unable to meet work, school, study, caregiving, or other obligations.

The original idea is intentionally simple: configure the relevant recipients once, then use one prominent action when illness makes ordinary communication difficult. AutoFever sends an appropriate absence message, records what was sent, and can later send a recovery or return notification.

> **Project status:** concept and incomplete Python prototype. This repository is not yet a production-ready or independently runnable application. See [Current Repository State](#current-repository-state).

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

1. select the preconfigured recipient groups;
2. optionally collect expected duration, return date, or a custom note;
3. generate the appropriate message for each audience;
4. show a concise final preview of recipients and disclosed information;
5. require an explicit send confirmation;
6. send immediately or place the notification in a durable offline queue;
7. display delivery and failure status without demanding further work from the user;
8. start an illness episode for later recovery follow-up.

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

Voice activation must still lead to a clear recipient-and-message confirmation before information is transmitted.

### Feedback and acknowledgment

The prototype anticipates optional recipient acknowledgment links. These must use short-lived, unguessable, single-purpose tokens and reveal the minimum possible information. Acknowledgments are optional and cannot be treated as proof that an employer, school, or other institution formally accepted an absence.

## Privacy, Security, and Safety

Illness information can be health data and therefore requires particularly careful treatment. A production implementation must include:

- data minimization and purpose limitation;
- device-first processing where practical;
- encryption at rest and in transit;
- explicit authorization for recipients, channels, and integrations;
- a final disclosure preview before sending;
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

## Current Repository State

The repository currently contains an incomplete prototype rather than a coherent application distribution.

### AutoFever material

- `app_enhanced_optimized_fixed.py` sketches the main application, Flask endpoints, illness and recovery flows, offline behavior, accessibility, personalization, feedback, and resource optimization.
- `code_review_findings.md` records issues found during an earlier review.
- `code_fixes_report.md` describes intended fixes and optimizations.

The main AutoFever file imports `models` and `services` modules that are not present in this repository. Templates, dependency metadata, packaging, migrations, and a runnable test suite are also absent. The prototype therefore cannot currently be installed and run from this checkout alone.

### Validation caution

The existing fix report says that tests passed in an earlier environment, but the corresponding complete source tree and test suite are not present here. Those claims cannot be independently reproduced from the current repository.

## Running the Project

There is currently no supported installation or run procedure. Do not treat the standalone Python files as a production deployment.

Before adding run instructions, the repository needs:

1. restoration of all required AutoFever modules and templates;
2. a dependency and lock file;
3. environment-variable documentation;
4. database and migration setup where required;
5. automated tests;
6. a reproducible local development command;
7. a production security review.

## Minimum Viable Product

The first credible release should contain:

- guided setup for identity, contacts, groups, and templates;
- one prominent illness action;
- optional duration, return date, and custom note;
- final recipient and disclosure confirmation;
- at least one reliable delivery adapter;
- encrypted local configuration;
- offline queue and duplicate-send prevention;
- delivery and failure status;
- explicit recovery notification;
- accessible mobile-first interface;
- complete deletion and export controls;
- no diagnostic or automated health inference.

Formal attendance-system integration should be introduced only after the core notification flow is reliable and an institution offers an authorized integration method.

## Acceptance Criteria

A release is not ready until:

1. no notification can be sent without an explicit, reviewable user action;
2. the final preview accurately lists every recipient, channel, and disclosed field;
3. queued retries cannot produce duplicate messages;
4. offline and restart recovery are tested;
5. delivery, acknowledgment, and formal absence acceptance remain distinct states;
6. illness mode and recovery mode form a consistent state machine;
7. accessibility flows work without a mouse and with a screen reader;
8. secrets and provider credentials are never committed to the repository;
9. health and contact data can be exported and deleted;
10. automated tests cover recipient resolution, template rendering, consent, retries, and adapter failures;
11. security and privacy documentation reflects the actual implementation;
12. the repository can be installed and run from documented steps in a clean environment.

## Roadmap

### Phase 1 — Repository recovery

- restore the missing AutoFever modules, templates, and tests;
- establish reproducible development tooling.

### Phase 2 — Private MVP

- implement the one-action illness and recovery flows;
- deliver through one reliable channel;
- validate usability, consent, offline behavior, and accessibility.

### Phase 3 — Integrations

- add channel adapters;
- add authorized calendar, workplace, school, and attendance integrations;
- normalize provider callbacks and delivery evidence.

### Phase 4 — Wider release

- complete privacy and security assessment;
- localize templates and onboarding;
- validate platform-store requirements;
- conduct controlled user testing before public availability.

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
