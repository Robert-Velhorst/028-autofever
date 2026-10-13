# Verification checkpoints

## Clean-history integration — 2026-10-13

The 12 preview source, documentation and test files were copied individually onto a fresh checkout of clean remote main `4709163f005f4068cd4c94b81a1f207d51fb94c0`. SHA-256 comparisons verified every copy before documentation updates. No old commits, vehicle implementation, contact data, browser storage or environment files were imported. The September evidence below is historical; fresh rerun results are recorded separately after execution.

Fresh execution on 13 October 2026: `./illness-preview/verify.ps1 -BaseUrl http://127.0.0.1:50170/` completed with exit status 0, six explicit browser-suite PASS results and the five-case runner contract PASS. The independently started Python 3 loopback server served this clean checkout, not a companion copy. Test tooling used Node.js 25.2.1 and the existing pinned Playwright CLI 0.1.19. No notification provider or real recipients were involved. The result is local Chromium evidence, not CI, phone-device or production acceptance.

## Original local checkpoint — 2026-09-05

## Scope

Robert approved the eight improvement areas discussed in the conversation. This checkpoint records implemented local improvements, not completion of the full goal.

| Area | Evidence / current result | Remaining |
| --- | --- | --- |
| 1. Shorter profile settings | Four collapsible sections, live summaries, mobile screenshot reviewed | Usability evaluation by Robert |
| 2. Preserve unsaved input | Browser tests for profile, contact and update drafts across navigation/reload; publishing kept separate; discard preserves saved profile | Same-draft concurrent edits are not merged |
| 3. Optional custom messages | Hidden by default, opt-in editor, effective-message preview; activation checked with per-person text | Full provider rendering tests |
| 4. Readiness before activation | Missing email/phone/task assignments listed on home; invalid email contact save rejected; recipient count visible | Channel connectivity and actual destination verification |
| 5. Concrete help requests | Timing, repeat preference and backup included in saved/activated snapshot | Private recipient action links; real requested/accepted/completed state transitions |
| 6. Honest automation status | Not sent, not acknowledged, not requested and reminder-not-planned copy; no fake delivery state | Real transport, job processing, retry/fallback, acknowledgements, recovery notifications |
| 7. Backup and restore | Real encrypted download/restore; wrong passphrase and altered ciphertext rejected; existing input kept on stale-tab save | Broader browser/recovery threat testing, lifecycle retention/export/delete policies |
| 8. Mobile accessibility | No horizontal overflow at 320/390/430/1280; page/new-task focus; stale-scroll fix; separate save region; rendered obstruction test; saved larger text/high contrast and keyboard activation | Physical iOS/Android, real virtual keyboard, 200% browser zoom and screen-reader verification |

## Executed checks

The browser tests use new isolated Chromium contexts with synthetic contacts. They do not change Robert's in-app browser data or send messages.

- `outputs/mobile-refinement-qa.js`: five scenarios covering separate draft persistence, optional custom message, contact validation/draft recovery, readiness and heading focus. All five initially failed against the old preview and passed after implementation.
- `outputs/mobile-help-backup-qa.js`: task timing/repeat/backup, truthful inactive delivery state, encrypted download, altered-ciphertext rejection, wrong-password rejection, confirmed restore and responsive widths.
- `outputs/mobile-refinement-regression-qa.js`: task add/remove without input loss, task focus, per-person message, HTML escaping, update draft/reload, recovery, explicit discard and reopening scroll position.
- `outputs/mobile-dock-qa.js`: visible form controls not obscured by save controls; all four sections can be reached and opened. Initially reproduced obscured sections before the separate editor dock was implemented.
- `outputs/mobile-multitab-qa.js`: stale tab cannot overwrite another tab's saved profile, reports the conflict and retains its current input. Reproduced actual overwriting before revision checks were added.

The original five suites completed successfully together using `outputs/verify-mobile-refinements.ps1` from the enclosing Codex workspace. They are now also included under this directory's `tests/`, without author-specific paths, session keys or screenshot destinations. `verify.ps1` runs those suites plus `tests/accessibility.js` against a supplied loopback URL using pinned Playwright CLI 0.1.19. It uses its own browser session and isolated test contexts. All six suites passed against the repository source served by Python's static development server, independently of the visual companion. CI has not yet been configured or run remotely. Relevant tested contexts reported no page exceptions. No claim is made about the unrelated root application's build or tests.

The accessibility suite checks keyboard activation of a preference and a collapsible section, persistence of both preferences, enlargement of actual text inputs, turning the options off, and editor/page reflow at 320×568, 390×430, 430×844 and 1280×800. A reduced-height viewport is not claimed as proof of a real phone's virtual-keyboard behavior. The backup suite also verifies that restoring a backup preserves the larger-text preference.

`tests/runner-contract.ps1` checks the actual runner function against five process-output cases: absent result, a tool error despite zero exit status, duplicate results, nonzero exit status and exactly one valid success result. The absent-result case failed before hardening because the runner accepted it. It passes after the runner was changed to reject anything other than one explicit successful result from each suite. A separate browser fixture also reproduced the old false-success behavior with six callbacks that returned `NO_TESTS_EXECUTED`; no assertion is made that those callbacks tested the app.

## Publication boundary at the September checkpoint

`index.html` is the repository source. The visual companion serves its `mobile-accessible.html` copy at the same localhost port 61765, preserving the existing browser origin and stored data. A first visit to that companion requires its complete session-key URL; the independent Python test server does not. This directory has not been committed, pushed or deployed. No credentials, hosting or notification provider have been connected by this work.

The October integration adds this source to the clean repository and updates the root README. Before calling the full user goal complete, build and verify the real notification/help/recovery chain, resolve hosting/provider setup, and perform the remaining accessibility checks. Do not mark the whole goal complete based on passing local UI tests or source publication.
