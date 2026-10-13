# Contributing

## Scope and source of truth

Autofever is the supported product: the mobile-first app in `illness-preview/`
and its optional service in `backend/`. The root Python prototype and its old
validation script are retired; do not extend them or create another owner,
recipient, storage, notification, or recovery implementation alongside the
maintained paths. Read the nearest feature guide and tests before changing a
contract.

GitHub issues are the implementation backlog. Link every implementation pull
request to its stable `[Sx-yy]` issue (and GitHub issue number), and keep the
change within its acceptance criteria. Roadmap labels, milestones and the
status board are not yet normalized; do not treat those views as authoritative.

## Implementation and review

- Describe the user-visible behavior and the regression the change prevents.
- State which existing implementation is reused, extended, replaced, or why no
  existing implementation applies. A second path for the same capability needs
  an explicit design reason and review.
- Add a meaningful test for the behavior and its failure/authorization boundary.
  Automated tests must use synthetic data and local/injected providers only;
  never send a live message, access production data, or mutate an external
  provider.
- Call out changes to authentication, health data, personal data retention,
  credentials, external delivery, deployment, or public exposure. Include the
  relevant privacy/security review and negative tests.
- Report the exact commands and outcomes. Separate local/CI evidence from
  public HTTPS, real-provider, physical-device, and production-host acceptance.
- Preserve the independent `013-hire-ai` service, data, credentials, routing and
  lifecycle. Autofever belongs in its own `028-autofever` paths and state.

`CODEOWNERS` requests review from the repository owner for the maintained app,
service, deployment and workflow paths. A direct GitHub API check on 2026-10-14
reported that `main` is not branch-protected. Required checks and code-owner
review therefore are not enforced until an authorized maintainer configures
branch protection separately.
