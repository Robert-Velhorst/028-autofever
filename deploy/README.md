# Hetzner deployment preparation

Target: run the separate application **028-autofever on the existing Hetzner server 013-hire-ai**. Preserve its hostname, Hire.ai installation, proxy routes, databases, credentials, volumes and service lifecycle. These files do not provision a server or deploy anything. No live host, domain or provider acceptance is claimed.

## Architecture and isolation

```text
Authorized HTTPS hostname
  -> existing host reverse proxy, with one dedicated Autofever site
     -> 127.0.0.1:28028: Waitress + HostedApp
        -> dedicated encrypted SQLite: /var/lib/028-autofever/state.sqlite3

Separately configured SMTP worker -> same dedicated store -> approved provider
Private operator tools           -> same store and OS dispatch lock
```

The proposed port must be checked for availability on the real host. It is not publicly published. The reverse proxy terminates TLS; the application accepts only loopback requests with a separate proxy credential, an exact configured host, an HTTPS assertion and a single valid client IP. Client-supplied forwarding headers do not choose the app origin or bypass authorization. The proxy must **overwrite**, not append, its four Autofever headers. This is a same-host trust boundary, not protection from the server's root administrator.

The web process does not send mail, provision owners, reconcile sends, expose files/directories or automatically schedule illness reminders. The SMTP worker remains opt-in, with separately approved configuration and recipient scope. Do not start it during web-only acceptance.

Proposed paths and identities, all separate from Hire.ai:

| Item | Dedicated value |
| --- | --- |
| Linux service user/group | `autofever` (non-login, unprivileged) |
| Versioned read-only application releases | `/opt/028-autofever/releases/<verified-commit>` |
| Active application pointer | `/opt/028-autofever/current` |
| Private mutable store and dispatch-lock sidecar | `/var/lib/028-autofever/` |
| Root-managed configuration/credential sources | `/etc/028-autofever/` |
| Web service unit | `028-autofever-web.service` |
| Operator/key backups | Separately protected destination chosen and tested before cutover |

Use local storage with real file-lock semantics; no NFS/SMB shared SQLite. All dispatch/reconciliation processes must use the same canonical database path and current lock implementation. The web service may run alongside the worker, but never run old and new sender versions concurrently during an upgrade.

## What is provided

- `backend.hosted`: separate Waitress entry point. It leaves `backend.local` and its loopback development-origin checks intact. It serves the existing owner/recipient interfaces and their existing capability-scoped APIs.
- [028-autofever-web.service](028-autofever-web.service): **reviewable systemd template**, not installed or validated against the actual host's systemd version. It uses a dedicated user, read-only system/home isolation, private temporary space, no capabilities, restrictive umask and a dedicated writable data path. Initial caps are 256 MiB memory, 50% of one CPU and 32 tasks; these are conservative testable limits, not measured capacity guarantees. Do not increase paid capacity automatically.
- [web.env.example](web.env.example): non-secret origin example. Replace `.invalid` only with an authorized actual hostname.
- [Caddyfile.autofever.example](Caddyfile.autofever.example): a single-site fragment for an **existing Caddy installation**, with TLS, a 2 MiB body ceiling, private health-route blocking and the required upstream headers. It must not replace the shared Caddyfile. If the host uses another proxy, implement and test the same contract in that existing proxy; do not install a competing listener on ports 80/443.
- [Dockerfile.test](Dockerfile.test): a pinned-base Linux test image, **not a deployment image**. It copies only selected source/assets/tests, runs non-root and has no embedded private config, database or key. Do not run this image as the production service.

## Local and Linux verification

Checkpoint, 13 October 2026: the current suite runs **142 backend cases**. Windows/Python 3.11.15 passes with one symlink-permission skip; non-root Linux x86_64/Python 3.11.17 passes all 142 without skips. Both runs treat resource warnings as errors and finish without background-thread exceptions. The suite includes the 98-case service/HTTP/SMTP/reconciliation/hosted baseline, 24 backup cases, 17 provisioning cases and three cross-version crypto compatibility cases. Actual process-death, hot-journal recovery, owner HTTP, restore quarantine and POSIX file-permission paths are covered with synthetic fixtures.

The earlier Docker outage is no longer a verification blocker: a fresh image was built and explicitly loaded after the engine recovered. Verified local image identity: `sha256:d39290f86e08dd3a06d3873727cee794ce4355c3ab05aa2daf0e51c54407b3d3`, user `1028:1028`. The Linux run had no external network, host mounts or published ports, a read-only root filesystem, a bounded temporary filesystem, dropped capabilities and no-new-privileges. SHA-256 checks of the requirement pin, compatibility/hosted tests, provisioning and backup modules matched the checkout before tests. The shared Docker environment was not restarted by this work.

Both tested platforms use cryptography **50.0.2** (bundled OpenSSL 4.0.3), Waitress 3.0.2, cffi 2.1.1 and pycparser 3.11. `pip check` passes on both; the read-only Linux image reports its pip cache disabled, not a dependency error. The unchanged Caddy fragment previously passed `caddy validate` using image digest `sha256:d8542f48d34a9cf4e4c11a478865229840e87e4c96ea3f439101f31a5d35f75f` and synthetic configuration. No public listener or real TLS certificate was created. The systemd template has not been installed or executed on the target host.

The [dependency security checkpoint](../backend/dependency-security.md) records the four cryptography advisories, the patched pin, a before/after known-vulnerability audit and successful use of a database/backup created before the upgrade. The updated four-package runtime inventory has no reported vulnerabilities in that audit. This does not scan the host OS/base image or prove production security. GitHub alert indexing and full release/host qualification are separate checks; alerts are not manually dismissed.

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

Building downloads public dependencies; running the tests uses no external network, host mounts or published ports. Temporary certificates, synthetic recipients and databases stay inside the disposable container. The base image is pinned by digest; application dependencies are version-pinned directly, but the complete transitive dependency set is not yet a hash-locked release manifest. Scan and qualify the release on the target Linux architecture before deployment.

The hosted transport tests exercise a real loopback Waitress socket, successful owner activation, blocked direct requests, private health, request/header limits, origin/auth isolation and rate limits. This is not a public TLS/browser/device test. Caddy configuration validation proves syntax/provisioning only; it does not prove DNS ownership, certificate issuance, running upstream behavior or shared-host safety.

## Credentials and startup

The web entry point requires **two different 32-byte secrets**, each stored as 64 lowercase hexadecimal characters in a private file: the existing store encryption key and an independent proxy key. The latter must match the value injected by the reverse proxy. Never reuse Hire.ai credentials or the database key as the proxy key. Files must be regular, nonsymlink and bounded; on POSIX, group/other permission bits are rejected. Windows ACLs require separate operator verification. Keep credential sources out of the repo and shell history.

The systemd template uses `LoadCredential` to pass root-managed sources into a service-private runtime directory. Confirm support and permissions on the target system. A private Caddy environment configuration must supply `AUTOFEVER_HOST` and `AUTOFEVER_PROXY_KEY` without exposing them in logs or configuration dumps. This guide does not install or modify a shared Caddy unit/environment.

After trusted provisioning of a dedicated store and owner capability, use local validation first (paths are illustrative):

```sh
backend/.venv/bin/python -m backend.hosted --database /var/lib/028-autofever/state.sqlite3 --key-file /private/store-key --proxy-key-file /private/proxy-key --origin https://autofever.example.invalid --check
```

`--check` reads/validates configuration and the existing store, without opening a listening socket or contacting a provider. It does not prove the proxy, hostname, credentials transfer or capacity. `--serve` explicitly starts the loopback server instead. No startup mode is implicit, no database is silently created and no owner capability is printed. Initial trusted store/owner provisioning now has a [dedicated local CLI](../backend/provisioning.md) with private output files and explicit crash-safe resume. Nontechnical onboarding/transfer, credential rotation/revocation and device recovery are separate unfinished work.

## Request limits, health and logs

The initial single web process uses four threads, 64 active connections, a backlog of 32, 16 KiB request headers and a 2 MiB body ceiling. Inactive connections expire after 15 seconds. These are not an overall transaction deadline or a defense against every slow-client/resource-exhaustion pattern; the public edge still needs reviewed timeouts and protections.

The application enforces fixed 60-second windows starting with each key's first accepted request: 600 requests globally, 120 per client IP and 60 per syntactically valid bearer token. Counters are atomic across threads, keys are HMAC-hashed with a process-random salt, and at most 4096 buckets are retained. Full limiter capacity returns 503; quota exhaustion returns 429 with `Retry-After: 60`. It does not silently evict live buckets to accept more traffic. Restarts reset counters; multiple web processes would multiply quotas. Use **one web process** until a shared limiter is implemented. Shared networks may hit the IP limit; deliberate global quota exhaustion can deny availability. These limits require usability/load qualification, not blind expansion.

`GET /_health` requires the same local proxy contract and verifies that the live database key-check can be decrypted. Success returns only `{"status":"ready"}`; failure is generic. The public Caddy fragment blocks this route. An internal monitor must use the private proxy header contract and exact Host. It must not log its credentials or call an owner activation endpoint as a health check. Readiness does not prove worker operation, mail delivery, sufficient disk space or backup freshness.

Responses retain no-store/referrer/CSP/framing protections. Existing recipient capabilities stay in fragments until the page removes them; they are not query parameters. Waitress transport logs are reduced to generic events with severity retained, and socket tracebacks are disabled. This sacrifices detailed transport diagnostics to avoid request-path/exception leakage. Audit **existing proxy access/error logs, global logging, infrastructure telemetry and retention** before exposing this app: application filtering cannot sanitize those external systems. The owner page still permits inline styles from the existing mobile editor; scripts use exact content hashes.

## Host acceptance and deployment sequence — not yet performed

1. Authenticate to the existing `013-hire-ai` host. Read-only inventory: OS/architecture, systemd/proxy versions, service names, occupied ports, firewall, filesystem ownership, disk/inodes, memory/CPU/swap and Hire.ai health baseline. Do not rename the host, stop Hire.ai or alter its databases.
2. Record actual capacity and choose the dedicated Autofever domain, paths and user. Resolve collisions explicitly. Confirm approval for any domain change, public exposure, paid provider or capacity cost before applying it.
3. Validate the release on that Linux architecture; review dependency/security results. Install into a new release directory with an isolated Python virtual environment. Source/venv should be root-owned and not writable by the runtime user. Provision only Autofever's dedicated state/config directories and credentials.
4. Keep external SMTP sending off. Validate the standalone configuration and systemd unit (`systemd-analyze verify` on the target), then test starting/stopping/restarting Autofever under the actual unit protections. This repository has not proven those host-specific operations.
5. Back up and validate the **entire existing proxy configuration** before adding only the Autofever site. Confirm the actual hostname is controlled and DNS points to the intended host. Validate without dumping secret-bearing expanded config; reload the existing proxy only after its full configuration passes. Preserve Hire.ai routes and immediately recheck its baseline.
6. Test the actual HTTPS owner/helper flows on a physical phone, including link expiry, cross-origin rejection, accessibility, offline/retry behavior and recovery. Confirm public health/admin/dispatch/reconcile routes are inaccessible, private ports are not externally reachable, logs do not expose data and rate limits behave under concurrency/load. Public TLS/browser proof is still missing.
7. Verify backups/restores and rollback below. Only then qualify a separately authorized email account/sender and controlled real-recipient test using [SMTP guidance](../backend/smtp.md). An HTTP page loading is not message delivery.

## Data, backups and rollback

There is no migration from Hire.ai. Never connect Autofever to its database or copy its secrets. The historical Python prototype and browser-only preview are not a production server database. Browser profile backups exclude server credentials and pending server actions; do not mistake restoring a profile for restoring server episodes.

The [server backup CLI](../backend/backups.md) now implements consistent encrypted SQLite snapshots, record/integrity verification and no-overwrite restore copies. Every restored copy has a persistent application hold before publication; it cannot serve personal records or send messages. Before any cutover, still implement and verify off-host scheduling, separately protected encryption-key recovery, retention, operator access and safe promotion of a restored copy. An ad-hoc copy of a live SQLite file is not the accepted backup procedure. No automated production backup or live restore has been installed or proven by this change. These remain release gates.

For a release rollback, stop Autofever's web/worker processes, preserve the current dedicated state, verify schema/runtime compatibility, repoint only Autofever's release pointer and restart only its units. Do not run an old sender version that ignores the dispatch lock alongside a new worker, or an old release that ignores `restore-hold` against a restored copy. Reverting source must not revert recorded send outcomes.

Restoring an older database can revive already-sent jobs and revoked links; newer episodes may be absent entirely. Keep **all application access and sending disabled** after a restore. The new tool enforces this in current application code. Do not bypass its hold; there is no release switch yet. A future cutover must account for authoritative provider evidence and the entire post-snapshot interval, not simply reset uncertain jobs. Verify the private copy offline and design/prove owner access and recipient isolation before promotion. If a proxy change caused a problem, restore only the reviewed Autofever routing change without discarding concurrent changes or harming Hire.ai. No rollback or data-loss scenario has been executed on the real host.

Sources for the selected components: [Waitress configuration](https://docs.pylonsproject.org/projects/waitress/en/stable/arguments.html), [Caddy reverse-proxy headers](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy). These document component behavior, not an Autofever production certification.
