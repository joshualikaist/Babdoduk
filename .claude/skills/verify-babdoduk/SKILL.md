---
name: verify-babdoduk
description: Run and interpret Babdoduk's four verification gates (pytest, content validator, site UI checker, food-hub UI checker). Use the relevant subset while iterating and all four before a handoff or release that changes frontend or product behavior.
---

# Verify Babdoduk

Run from the repository root, one gate at a time, because parallel browser runs compete for the CPU.

| Gate | Command | Time |
| --- | --- | --- |
| Tests (unit, contracts, UI; includes a full site-UI run) | `python -m pytest tests -q` | ~90 s |
| Generated content | `python scripts/validate_content.py` | seconds |
| Site UI: every public page, 5 sizes, KO/EN, failures | `python scripts/check_site_ui.py` | ~60 s |
| Food hub UI: fixture, preview and production pages | `python scripts/check_ggongbab_ui.py` | ~20 s |

`pytest.ini` sets `addopts = -q`. Add `-o addopts=""` to get the "N passed" line. The browser checks use installed Chrome through Playwright. They never call live accounts or databases.

## Which gates

`AGENTS.md` ("Verification by change type") decides which gates a change needs:
- **While iterating:** run the test file you touched (`python -m pytest tests/<file> -q`) and the checker for the page you changed.
- **Before a handoff or release that changes frontend or product behavior:** run all four.
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
