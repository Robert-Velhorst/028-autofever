# Hetzner deployment preparation

Target: run the separate application **028-autofever on the existing Hetzner server 013-hire-ai**. Preserve its hostname, Hire.ai installation, proxy routes, databases, credentials, volumes and service lifecycle. These files do not provision a server or deploy anything. No live host, domain or provider acceptance is claimed.

## Architecture and isolation

```text
Authorized HTTPS hostname
  -> existing host reverse proxy, with one dedicated Autofever site
     -> 127.0.0.1:28028: Waitress + HostedApp
        -> dedicated encrypted SQLite: /var/lib/028-autofever/state.sqlite3

Optional 028-autofever-worker.service -> same dedicated store -> approved SMTP provider
Private operator tools           -> same store and OS dispatch lock
```

The proposed port must be checked for availability on the real host. It is not publicly published. The reverse proxy terminates TLS; the application accepts only loopback requests with a separate proxy credential, an exact configured host, an HTTPS assertion and a single valid client IP. Client-supplied forwarding headers do not choose the app origin or bypass authorization. The proxy must **overwrite**, not append, its four Autofever headers. This is a same-host trust boundary, not protection from the server's root administrator.

The web process does not send mail, provision owners, reconcile sends, expose files/directories or automatically schedule illness reminders. The SMTP worker unit is a separate, opt-in template; it is not installed or enabled by this repository. Once explicitly configured and started, it processes only already-queued illness, recovery and owner-authored update emails. Check-in due state and confirmation never enqueue a message, and no check-in reminder is sent. Do not start the worker during web-only acceptance or before the provider, sender identity, recipient allowlist, public help origin, private credentials and delivery procedures are approved.

Proposed paths and identities, all separate from Hire.ai:

| Item | Dedicated value |
| --- | --- |
| Linux service user/group | `autofever` (non-login, unprivileged) |
| Versioned read-only application releases | `/opt/028-autofever/releases/<verified-commit>` |
| Active application pointer | `/opt/028-autofever/current` |
| Private mutable store and dispatch-lock sidecar | `/var/lib/028-autofever/` |
| Root-managed configuration/credential sources | `/etc/028-autofever/` |
| Web service unit | `028-autofever-web.service` |
| Optional daily live-history cleanup | `028-autofever-retention.service` + `.timer` |
| Operator/key backups | Separately protected destination chosen and tested before cutover |

Use local storage with real file-lock semantics; no NFS/SMB shared SQLite. All dispatch/reconciliation processes must use the same canonical database path and current lock implementation. The web service may run alongside the worker, but never run old and new sender versions concurrently during an upgrade.

## What is provided

- `backend.hosted`: separate Waitress entry point. It leaves `backend.local` and its loopback development-origin checks intact. It serves the existing owner/recipient interfaces and their existing capability-scoped APIs.
- [028-autofever-web.service](028-autofever-web.service): **reviewable systemd template**, not installed or validated against the actual host's systemd version. It uses a dedicated user, read-only system/home isolation, private temporary space, no capabilities, restrictive umask and a dedicated writable data path. Initial caps are 256 MiB memory, 50% of one CPU and 32 tasks; these are conservative testable limits, not measured capacity guarantees. Do not increase paid capacity automatically.
- [028-autofever-worker.service](028-autofever-worker.service): **reviewable optional sender template**, not installed or enabled. It runs the existing worker in explicit continuous send mode, loads the store key, SMTP password and private SMTP configuration through systemd credentials, and is restricted to the same dedicated data path. It does not process check-ins. Enable it only after separately approving and qualifying real outbound email; never enable it for web-only acceptance.
- [028-autofever-retention.service](028-autofever-retention.service) and [028-autofever-retention.timer](028-autofever-retention.timer): **reviewable templates**, not installed or validated on the host. The daily bounded cleanup is inert unless an owner opts into a period; it skips active episodes and unresolved sends and shares the dispatch lock. Review the feature contract in [backend/retention.md](../backend/retention.md). Do not enable before confirming the target service paths, credentials, systemd support and backup boundaries.
- [web.env.example](web.env.example): non-secret origin example. Replace `.invalid` only with an authorized actual hostname.
- [Caddyfile.autofever.example](Caddyfile.autofever.example): a single-site fragment for an **existing Caddy installation**, with TLS, a 2 MiB body ceiling, private health-route blocking and the required upstream headers. It must not replace the shared Caddyfile. If the host uses another proxy, implement and test the same contract in that existing proxy; do not install a competing listener on ports 80/443.
- [Dockerfile.test](Dockerfile.test): a pinned-base Linux test image, **not a deployment image**. It copies only selected source/assets/tests, runs non-root and has no embedded private config, database or key. Do not run this image as the production service.

## Local and Linux verification

Before any target-host change, an operator can run `python3 deploy/host_preflight.py --port 28028` over SSH. It emits JSON containing a bounded OS/CPU/memory/disk snapshot, relevant running service-unit names, installed proxy versions, existing Autofever path metadata and any listener observed on the candidate port. The script does not read proxy configuration or secret values, write files, change services, or contact external systems. The report includes host identity and infrastructure metadata, so keep it private. A free-looking port is only a momentary observation and is not reserved; the report is not host acceptance. The operator must still authenticate the host identity, identify Hire.ai's actual service and proxy routes, verify DNS/firewall/health, and resolve all path/domain/capacity choices before installation.

Checkpoint, 13 October 2026: the current suite runs **188 backend cases** (187 passed; one platform-dependent symlink check was skipped on Windows). Windows/Python 3.11.15 passed locally in 99.191 seconds. GitHub Actions run [38453703154](https://github.com/Robert-Velhorst/028-autofever/actions/runs/38453703154), on commit `8d50d2b`, passes the standard Linux backend job (`pip check` and all 188 tests), the hardened isolated-container job (the same test suite), and all eight mobile browser suites on Windows. These jobs test synthetic/local behavior; they do not deploy or send real messages. Resource warnings are errors in the standard backend job. The suite includes the lifecycle, transport, backup, provisioning, access, crypto, updates, retention, migration, SMTP and owner-deletion cases. Synthetic tests cover queue preservation, selected-recipient isolation, immutable update selection, concurrent/replayed commands, migration rollback, v2 revocation preservation, local TLS submission, closure-anchored retention, check-ins remaining in-app-only and fail-closed server-data deletion. A separate check loaded the actual service source from commit `3327793`: after migrating a synthetic v1 store to v3, that previous runtime refused both startup and requests through an existing Store instance.

Follow-up checkpoint, 14 October 2026: commit `23829f1` is verified by GitHub Actions run [38480178231](https://github.com/Robert-Velhorst/028-autofever/actions/runs/38480178231), which passed all 188 backend cases on Windows and Linux, the hardened isolated-container suite and ten Windows browser suites. CodeQL run [38480177739](https://github.com/Robert-Velhorst/028-autofever/actions/runs/38480177739) also succeeded. CI consumed the checked-in Python/OS matrix and installed the hash-locked backend dependencies. Browser verification for the preceding `.afaccess` feature covers wrong-passphrase rejection, no request before explicit confirmation, same-origin display and read-only authenticated restore. These are local/synthetic checks, not deployment, physical-phone or provider acceptance.

Latest feature checkpoint, 14 October 2026: commit `8a87441` adds a helper-only withdrawal action for an accepted task. Withdrawal is restricted to the current claimant before completion, returns the task to pending, and does not enqueue a message to other helpers. The full local backend suite passes 199 cases (198 passed; one platform-dependent case skipped), and all ten browser suites pass locally. GitHub Actions run [38487400901](https://github.com/Robert-Velhorst/028-autofever/actions/runs/38487400901) passed Linux backend tests and the isolated test-container job, but was cancelled by the subsequent README push before the Windows backend and browser jobs finished. CodeQL run [38487401443](https://github.com/Robert-Velhorst/028-autofever/actions/runs/38487401443) remained queued at the latest check. Hosted Windows/browser and CodeQL verification for this feature commit is therefore unconfirmed. No deployment, physical-phone acceptance or real-provider delivery was performed.

An earlier isolated test image was built and run against the **174-case** checkpoint as `autofever-tests:updates-20261013`, with inspected identity `sha256:4a663a7f45fc994a09b1581a93f9bc710a35203d726f757a03303728c7655d4b` and user `1028:1028`. The current [workflow](../.github/workflows/ci.yml) rebuilds its pinned test-only image from the checked-out commit and runs it with no network, host mounts or published ports, a read-only root filesystem, a bounded temporary filesystem, dropped capabilities, no-new-privileges, and CPU/memory limits. Run [38453703154](https://github.com/Robert-Velhorst/028-autofever/actions/runs/38453703154) passed this check for commit `8d50d2b`; it does not validate a production image, host, or deployment. No shared Docker restart or other project change was performed. The earlier crypto checkpoint used a separate verified image; its results remain recorded in the dependency report.

The [update UI flow](../backend/updates.md) also passed Chrome/Playwright checks on a temporary real loopback service at 320, 390 and 1280 CSS pixels. This includes saved drafts, lost replies after commit, exactly one queued update on retry/reload, personal-link switching with stale-response suppression, screenshots, clean app console and no external browser requests. No physical phone, live provider or public TLS route was used.

Both tested platforms use cryptography **50.0.2** (bundled OpenSSL 4.0.3), Waitress 3.0.2, cffi 2.1.1 and pycparser 3.11. `pip check` passes on both; the read-only Linux image reports its pip cache disabled, not a dependency error. The unchanged Caddy fragment previously passed `caddy validate` using image digest `sha256:d8542f48d34a9cf4e4c11a478865229840e87e4c96ea3f439101f31a5d35f75f` and synthetic configuration. No public listener or real TLS certificate was created. The systemd template has not been installed or executed on the target host.

The [dependency security checkpoint](../backend/dependency-security.md) records the four cryptography advisories, the patched pin, a before/after known-vulnerability audit and successful use of a database/backup created before the upgrade. The updated four-package runtime inventory has no reported vulnerabilities in that audit. GitHub now reports all four Dependabot alerts as automatically fixed after indexing cryptography 50.0.2; none was manually dismissed. This does not scan the host OS/base image or prove production security, and full release/host qualification remains separate.

Windows tests from the repository root:

```powershell
./backend/.venv/Scripts/python.exe -W error::ResourceWarning -m unittest discover -s backend/tests -q
./backend/.venv/Scripts/python.exe -m pip check
```

Build and run the isolated Linux test image:

```sh
docker build --load --file deploy/Dockerfile.test --tag autofever-tests:local .
docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --memory 512m --cpus 2 autofever-tests:local
```

Building downloads public dependencies; running the tests uses no external network, host mounts or published ports. Temporary certificates, synthetic recipients and databases stay inside the disposable container. The base image is pinned by digest. `backend/requirements.lock` hash-locks the complete four-package Python dependency graph for the supported CPython 3.11 targets, and installation enforces those hashes with `pip --require-hashes`. This covers the Python environment, not host operating-system packages or a production image. Scan and qualify the release on the target Linux architecture before deployment.

The hosted transport tests exercise a real loopback Waitress socket, successful owner activation, blocked direct requests, private health, request/header limits, origin/auth isolation and rate limits. This is not a public TLS/browser/device test. Caddy configuration validation proves syntax/provisioning only; it does not prove DNS ownership, certificate issuance, running upstream behavior or shared-host safety.

## Credentials and startup

The web entry point requires **two different 32-byte secrets**, each stored as 64 lowercase hexadecimal characters in a private file: the existing store encryption key and an independent proxy key. The latter must match the value injected by the reverse proxy. Never reuse Hire.ai credentials or the database key as the proxy key. Files must be regular, nonsymlink and bounded; on POSIX, group/other permission bits are rejected. Windows ACLs require separate operator verification. Keep credential sources out of the repo and shell history.

The optional worker separately consumes the store key, SMTP password and SMTP JSON configuration. Its systemd template declares all three as `LoadCredential` sources under `/etc/028-autofever/`; systemd passes private runtime copies to the process, not secret values in the command line or environment. Keep the source files root-managed and private, validate the exact allowlist and sender, and do not install or enable the unit until the operator has approved real provider use. `backend.worker --check` validates the credentials/configuration and existing store without connecting or consuming the queue.

The systemd template uses `LoadCredential` to pass root-managed sources into a service-private runtime directory. Confirm support and permissions on the target system. A private Caddy environment configuration must supply `AUTOFEVER_HOST` and `AUTOFEVER_PROXY_KEY` without exposing them in logs or configuration dumps. This guide does not install or modify a shared Caddy unit/environment.

After trusted provisioning of a dedicated store and owner capability, use local validation first (paths are illustrative):

```sh
backend/.venv/bin/python -m backend.hosted --database /var/lib/028-autofever/state.sqlite3 --key-file /private/store-key --proxy-key-file /private/proxy-key --origin https://autofever.example.invalid --check
```

`--check` reads/validates configuration and the existing store, without opening a listening socket or contacting a provider. It does not prove the proxy, hostname, credentials transfer or capacity. `--serve` explicitly starts the loopback server instead. No startup mode is implicit, no database is silently created and no owner capability is printed. Initial trusted store/owner provisioning now has a [dedicated local CLI](../backend/provisioning.md) with private output files and explicit crash-safe resume. A separate [access CLI](../backend/owner-access.md) replaces or revokes retained owner credentials. Nontechnical onboarding/transfer and recovery without retained credential files remain unfinished.

## Request limits, health and logs

The initial single web process uses four threads, 64 active connections, a backlog of 32, 16 KiB request headers and a 2 MiB body ceiling. Inactive connections expire after 15 seconds. These are not an overall transaction deadline or a defense against every slow-client/resource-exhaustion pattern; the public edge still needs reviewed timeouts and protections.

The application enforces fixed 60-second windows starting with each key's first accepted request: 600 requests globally, 120 per client IP and 60 per syntactically valid bearer token. Counters are atomic across threads, keys are HMAC-hashed with a process-random salt, and at most 4096 buckets are retained. Full limiter capacity returns 503; quota exhaustion returns 429 with `Retry-After: 60`. It does not silently evict live buckets to accept more traffic. Restarts reset counters; multiple web processes would multiply quotas. Use **one web process** until a shared limiter is implemented. Shared networks may hit the IP limit; deliberate global quota exhaustion can deny availability. These limits require usability/load qualification, not blind expansion.

`GET /_health` requires the same local proxy contract and verifies that the live database key-check can be decrypted. Success returns only `{"status":"ready"}`; failure is generic. The public Caddy fragment blocks this route. An internal monitor must use the private proxy header contract and exact Host. It must not log its credentials or call an owner activation endpoint as a health check. Readiness does not prove worker operation, mail delivery, sufficient disk space or backup freshness.

Responses retain no-store/referrer/CSP/framing protections. Existing recipient capabilities stay in fragments until the page removes them; they are not query parameters. Waitress transport logs are reduced to generic events with severity retained, and socket tracebacks are disabled. This sacrifices detailed transport diagnostics to avoid request-path/exception leakage. Audit **existing proxy access/error logs, global logging, infrastructure telemetry and retention** before exposing this app: application filtering cannot sanitize those external systems. The owner page still permits inline styles from the existing mobile editor; scripts use exact content hashes.

## Host acceptance and deployment sequence — not yet performed

1. Authenticate to the existing `013-hire-ai` host. Read-only inventory: OS/architecture, systemd/proxy versions, service names, occupied ports, firewall, filesystem ownership, disk/inodes, memory/CPU/swap and Hire.ai health baseline. Do not rename the host, stop Hire.ai or alter its databases.
2. Record actual capacity and choose the dedicated Autofever domain, paths and user. Resolve collisions explicitly. Confirm approval for any domain change, public exposure, paid provider or capacity cost before applying it.
3. Validate the release on that Linux architecture; review dependency/security results. Install into a new release directory with an isolated Python virtual environment. Source/venv should be root-owned and not writable by the runtime user. Provision only Autofever's dedicated state/config directories and credentials.
4. Keep external SMTP sending off. Validate the standalone configuration and all provided systemd service/timer templates (`systemd-analyze verify` on the target), then test the web unit under its actual protections. Keep the worker unit stopped and disabled during web-only acceptance. Enable the retention timer only after confirming the documented owner opt-in and backup boundaries; run its non-destructive `--check` first. This repository has not proven those host-specific operations.
5. Back up and validate the **entire existing proxy configuration** before adding only the Autofever site. Confirm the actual hostname is controlled and DNS points to the intended host. Validate without dumping secret-bearing expanded config; reload the existing proxy only after its full configuration passes. Preserve Hire.ai routes and immediately recheck its baseline.
6. Test the actual HTTPS owner/helper flows on a physical phone, including link expiry, cross-origin rejection, accessibility, offline/retry behavior and recovery. Confirm public health/admin/dispatch/reconcile routes are inaccessible, private ports are not externally reachable, logs do not expose data and rate limits behave under concurrency/load. Public TLS/browser proof is still missing.
7. Verify backups/restores and rollback below. Only then qualify a separately authorized email account/sender and controlled real-recipient test using [SMTP guidance](../backend/smtp.md). Install and enable the worker only after that explicit provider/recipient acceptance. An HTTP page loading is not message delivery.

## Data, backups and rollback

There is no migration from Hire.ai. Never connect Autofever to its database or copy its secrets. The historical Python prototype and browser-only preview are not a production server database. Browser profile backups exclude server credentials and pending server actions; do not mistake restoring a profile for restoring server episodes.

The [server backup CLI](../backend/backups.md) now implements consistent encrypted SQLite snapshots, record/integrity verification and no-overwrite restore copies. Every restored copy has a persistent application hold before publication; it cannot serve personal records or send messages. Before any cutover, still implement and verify off-host backup scheduling/expiry, separately protected encryption-key recovery, retention-timer installation, operator access and safe promotion of a restored copy. An ad-hoc copy of a live SQLite file is not the accepted backup procedure. No automated production backup, retention run or live restore has been installed or proven by this change. These remain release gates.

For a release rollback, stop Autofever's web/worker processes, preserve the current dedicated state, verify schema/runtime compatibility, repoint only Autofever's release pointer and restart only its units. Do not run an old sender version that ignores the dispatch lock alongside a new worker, or an old release that ignores `restore-hold` against a restored copy. [Owner access changes](../backend/owner-access.md) require at least database version 2. [Explicit update support](../backend/updates.md#database-version-3-and-explicit-existing-store-migration) requires version 3, now used for new stores; older stores require the backup-first offline migration. Stop all old Autofever processes before migration and reload browser clients afterward. Rollback to code that ignores revocation or updates is forbidden. Never lower version markers or remove access/update records. Reverting source must not revert send outcomes or revive disabled credentials.

Restoring an older database can revive already-sent jobs and revoked links; newer episodes may be absent entirely. Keep **all application access and sending disabled** after a restore. The new tool enforces this in current application code. Do not bypass its hold; there is no release switch yet. A future cutover must account for authoritative provider evidence and the entire post-snapshot interval, not simply reset uncertain jobs. Verify the private copy offline and design/prove owner access and recipient isolation before promotion. If a proxy change caused a problem, restore only the reviewed Autofever routing change without discarding concurrent changes or harming Hire.ai. No rollback or data-loss scenario has been executed on the real host.

Sources for the selected components: [Waitress configuration](https://docs.pylonsproject.org/projects/waitress/en/stable/arguments.html), [Caddy reverse-proxy headers](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy). These document component behavior, not an Autofever production certification.
