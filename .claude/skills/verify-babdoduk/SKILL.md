---
name: verify-babdoduk
description: Run and interpret Babdoduk's five verification gates (pytest, content validator, shared chrome sync check, site UI checker, food-hub UI checker). Use the relevant subset while iterating and all five before a handoff or release that changes frontend or product behavior.
---

# Verify Babdoduk

Run from the repository root. One command runs the gates in the fastest safe way (owner 2026-11-12: a check
after every change took about 20 minutes, mostly the site-UI run done twice and one check after another):

| When | Command | What it runs | Time on the ops PC |
| --- | --- | --- | --- |
| Before a push to `lab` | `python scripts/check_all.py --quick` | chrome sync, content, every test except the full site-UI run, on parallel workers (`pytest-xdist`) | ~1 min |
| After the push | `python scripts/ci_status.py <commit> --wait` | GitHub's `tests` workflow: the whole suite including the site-UI run; `chrome-sync`; `visual-guardian` | read only |
| Before a production release (and its handoff) | `python scripts/check_all.py` | the five gates below, once each; the site-UI groups side by side | ~4 min |

The five gates it runs:

| Gate | Command | Time |
| --- | --- | --- |
| Tests (unit, contracts, UI), without the site-UI run | `python -m pytest tests -q -n 8 --deselect tests/test_site_ui.py::test_all_public_pages_windows_scrollbars_and_overflow` | ~55 s |
| Generated content | `python scripts/validate_content.py` | seconds |
| Shared nav, footer, translations, labels and page content match `shared/`, `i18n/` and `data/content/` | `python scripts/sync_site_chrome.py --check` | seconds |
| Site UI: every public page, 5 sizes, KO/EN, failures, chrome guardian (the deselected test; `scripts/check_site_ui.py` runs the same groups) | `python -m pytest tests/test_site_ui.py::test_all_public_pages_windows_scrollbars_and_overflow -q` | ~2.5 min |
| Food hub UI: fixture, preview and production pages | `python scripts/check_ggongbab_ui.py` | ~40 s |

`scripts/check_site_ui.py` runs its checks in ten independent groups, at most six side by side
(`--jobs`, `BABDODUK_SITE_UI_JOBS`; `--jobs 1` is the old one-after-another order). More than six made
timing checks fail from CPU load (the drawer's fixed 300 ms wait), so six is the cap. The chrome
screenshot comparison is skipped unless `check_all.py --visual`: baselines exist for the pinned CI
container and the owner's Windows PC, not this Linux PC, and ui-guardian compares them in CI.

`pytest.ini` sets `addopts = -q`. Add `-o addopts=""` to get the "N passed" line. The browser checks use installed Chrome through Playwright. They never call live accounts or databases.

The browser gates block web fonts to stay deterministic. For a change that affects layout or copy, also run the separate real-font smoke, `python scripts/check_real_fonts.py`. It needs the network for Google Fonts and reports PASS, FAIL (exit 1) or SKIP (exit 3, font not loaded, which proves nothing). Report a SKIP as a SKIP, never as a pass.

## Which gates

`AGENTS.md` ("Verification by change type") decides which gates a change needs:
- **While iterating:** run the test file you touched (`python -m pytest tests/<file> -q`) and the checker for the page you changed.
- **Before a push to `lab`:** `check_all.py --quick`, then read the commit's GitHub checks after the push. A failed GitHub check is a first result like any other: report it and fix it on the task branch.
- **Before a production release, or a handoff that ends one:** all five, `check_all.py`.
- **Documentation only:** check links and facts against the code; no browser gates.

## Failures are evidence

- Record every gate's first result exactly: exit code, counts and the failing statement. Never rerun until green and then report only the last run.
- Never weaken an assertion, fixture or timeout to get a pass. Fix the code, or fix a test that is actually wrong and explain why.
- Classify each failure with evidence:
  - **Regression:** the failing check exercises files this change touched (compare `git diff --name-only <base>` with what the check loads), or the failure reproduces.
  - **Pre-existing intermittent:** a known flake, and the failing check does not load the changed files. Report the first failure, its prior occurrences and the rerun result together.
- Known intermittent issues on this Windows machine:
  - `check_ggongbab_ui.py`'s first `.gg-card` wait in the production-page loop sometimes times out after 30 s. The occurrences so far coincided with host power or display transitions in the Windows event log.
  - `tests/ggongbab/test_ai_errors.py::test_transient_failure_recovers_on_retry` sometimes fails in a full run and passes in isolation.
- Tests prove the code under test. They do not prove that production, external services or data freshness are healthy, so say what was not tested.
