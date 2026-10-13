# Dependency security checkpoint — 13 October 2026

The backend pin is upgraded from `cryptography==46.0.7` to **`50.0.2`**.
This is a dependency remediation, not a claim that Autofever is production-ready
or free of all vulnerabilities. No production environment was upgraded.

## Findings and selected release

GitHub's Dependabot API reported these four open findings against
`backend/requirements.txt` before the change:

| Advisory | Reported severity | Affected area | First fixed version |
| --- | --- | --- | --- |
| [GHSA-537c-gmf6-5ccf](https://github.com/Robert-Velhorst/028-autofever/security/dependabot/1) | High | OpenSSL bundled in wheels | 48.0.1 |
| [GHSA-g6cj-pr64-35w5](https://github.com/Robert-Velhorst/028-autofever/security/dependabot/2) | High | PKCS#7 decryption oracle | 50.0.0 |
| [GHSA-jwv3-5hgf-82ww](https://github.com/Robert-Velhorst/028-autofever/security/dependabot/3) | High | Certificate path-building complexity | 49.0.0 |
| [GHSA-m2h6-j472-rp4c](https://github.com/Robert-Velhorst/028-autofever/security/dependabot/4) | Medium | Wildcard certificate constraints | 49.0.0 |

The [upstream release notes](https://cryptography.io/en/latest/changelog/)
identify `50.0.2` as the stable 30 September 2026 release, with wheels using
OpenSSL 4.0.3. PyPI availability and installation of the Windows x86_64 wheel
were verified. The development version `51.0.0-dev1` was not selected. Version
`50.0.2` lies outside all four reported affected ranges.

The application uses AES-GCM and HKDF-SHA256 in [service records](service.py)
and [archives](backup.py). SMTP integration tests also generate synthetic RSA
certificates. Inspection found no application PKCS#7 decryption or cryptography
X.509 path-verifier entry point; SMTP's TLS transport uses Python's `ssl` module.
This is scope evidence, **not** a basis for dismissing the alerts or asserting
that the old wheel was safe. Its bundled native library was also affected.

## Known-vulnerability audit

An isolated `pip-audit==2.10.1` tool environment queried the PyPI advisory service
for the four exact runtime packages, without installing the old vulnerable
package or automatically applying fixes:

```text
cryptography==50.0.2
waitress==3.0.2
cffi==2.1.1
pycparser==3.11
```

The audit used `--no-deps --disable-pip --strict --progress-spinner off --desc off
--format json` against an explicitly enumerated, fully pinned runtime inventory.
Transitive runtime packages were included explicitly; this is not a claim that
`--no-deps` discovers them. See [pip-audit's
documentation](https://github.com/pypa/pip-audit).

Results:

- Old inventory (`cryptography==46.0.7`): exit `1`; the raw feed returned seven
  records representing **four unique advisories**, including duplicates of three
  PYSEC IDs. Their aliases match the four GitHub findings above.
- Updated inventory: exit `0`; zero reported vulnerabilities for all four listed
  packages. No advisories were ignored. Two cache-deserialization warnings were
  logged and those cache entries were ignored; the completed JSON result includes
  all four requested packages without collection errors.
- `python -m pip check`: exit `0`, no broken requirements. This checks dependency
  consistency, not security.

This audit does not cover the host OS, Docker base-image packages, Python's own
TLS runtime, build tools, unrelated historical prototype dependencies or unknown
vulnerabilities. No custom exploit/timing/DoS reproducer was run for the upstream
bugs. Remediation evidence is the vendor's patched release, installed version,
advisory-range checks and the before/after audit—not a claim that every exploit
was reproduced locally. The GitHub fixed state was verified after publication;
none of the four alerts was manually dismissed.

## GitHub Dependabot status

Read directly from `GET /repos/Robert-Velhorst/028-autofever/dependabot/alerts`
on **13 October 2026**, GitHub returned `state: fixed`, with non-null `fixed_at`
for all four findings after the updated default-branch manifest was indexed:

| Alert | GitHub `fixed_at` (UTC) | First fixed version | Current pin |
| --- | --- | --- | --- |
| [#1 GHSA-537c-gmf6-5ccf](https://github.com/Robert-Velhorst/028-autofever/security/dependabot/1) | 10:50:58 | 48.0.1 | 50.0.2 |
| [#2 GHSA-g6cj-pr64-35w5](https://github.com/Robert-Velhorst/028-autofever/security/dependabot/2) | 10:50:58 | 50.0.0 | 50.0.2 |
| [#3 GHSA-jwv3-5hgf-82ww](https://github.com/Robert-Velhorst/028-autofever/security/dependabot/3) | 10:50:59 | 49.0.0 | 50.0.2 |
| [#4 GHSA-m2h6-j472-rp4c](https://github.com/Robert-Velhorst/028-autofever/security/dependabot/4) | 10:50:59 | 49.0.0 | 50.0.2 |

All four API records had `dismissed_at: null`. GitHub marked them fixed after
seeing the patched requirement. That finding does not certify the application,
host OS, container base image, production installation or future dependencies.

## Compatibility and regression evidence

Before upgrading, a disposable store was created with **46.0.7**, containing
synthetic owner enrollment, two accepted notifications, a recipient acknowledgment,
a claimed help task and an encrypted server backup. After upgrading to **50.0.2**:

- the same owner file authenticated;
- existing episode, queue and helper records matched their saved expected state;
- the old backup authenticated and restored into a persistently blocked copy;
- task completion and recovery worked, queuing exactly two recovery notices;
- no external message was sent.

The permanent [compatibility tests](tests/test_crypto_compatibility.py) retain a
known synthetic 46.0.7 ciphertext and HKDF-derived digest-key vector. They verify
decryption/key compatibility, rejection of a wrong key or record identity,
tampering and truncation, plus fresh nonce/roundtrip behavior. The test key is
intentionally public and must never be used for real data.

A Windows test-server shutdown race was observed during verification: the test
closed sockets from another thread while Waitress was in `select()`. The
[transport test](tests/test_hosted.py) now closes channels using Waitress's own
event-loop trigger and fails on captured server-thread errors. Production
transport code and authentication rules were not changed. Ten repeated real
Waitress HTTP cases passed after this test-only repair.

The full Windows/Python 3.11.15 run finished cleanly: **142 tests, one symlink
permission skip**, with resource warnings treated as errors. That is the previous
139-case suite plus three compatibility cases. The installed crypto backend
reported `50.0.2` and `OpenSSL 4.0.3 29 Sep 2026`. Current Linux results, image
identity and any remaining verification gap are recorded in the
[deployment checkpoint](../deploy/README.md#local-and-linux-verification).

The upgrade crosses upstream platform changes: 32-bit Windows and x86_64 macOS
support were removed in 49.0.0. Autofever's verified development target is
64-bit Windows; the intended server target is 64-bit Linux. Do not infer support
for other backend platforms from Python-version compatibility alone. Mobile
browsers access the web interface; this change does not install Python on phones.

Real-host deployment, provider acceptance, physical-device testing, complete
security review and the unfinished product capabilities remain separate gates.
