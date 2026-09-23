# Controlled integration / release checklist

## Before work

- [ ] Read AGENTS.md, PRD.md, DESIGN_SYSTEM.md, ARCHITECTURE.md and scoped docs.
- [ ] Record branch, HEAD, status, branches/worktrees, existing changes/stashes and locks.
- [ ] Fetch origin; record origin/main, origin/lab and ahead/behind counts.
- [ ] Use an isolated agent/<tool>/<task> or approved release/<name> worktree, one active agent only.
- [ ] Never stage, overwrite, stash or discard pre-existing user state.

## Candidate boundary

- [ ] Compare with pinned main, not a stale local main.
- [ ] Review explicit approved paths/manual ports; do not merge all of lab by default.
- [ ] Keep generated JSON, workflows, Supabase, Realtime, collectors and Windows operations out of Phase 10B.
- [ ] Preserve food-log localStorage and same-date precedence with source labels.
- [ ] Historical May occurrence stays 진행 여부 미확인.
- [ ] Picker stays integrated; lab.html/calendar.ics remain publicly present without redesign.
- [ ] No Privacy Policy/Terms, workflow recovery or magazine generator fix.

## Tests

- [ ] Full python -m pytest tests -q and python scripts/validate_content.py.
- [ ] python scripts/check_site_ui.py and python scripts/check_ggongbab_ui.py.
- [ ] Eight routes, mobile/tablet/desktop, long Korean/English text, Windows scrollbars, no body/footer overflow.
- [ ] Nav/keyboard/focus, languages, reduced motion, failure/stale states and saved filters.
- [ ] Fixture clock only on lab fixture route; normal/preview clocks stay native.
- [ ] No live Portal/Dooray/Supabase traffic as a test fixture.
- [ ] Report untested browsers, assistive technology, hosting and freshness honestly.

## Handoff

- [ ] Review git status, git diff and git diff --staged; stage task-owned paths only.
- [ ] Commit coherent work, using an agent trailer where appropriate.
- [ ] Fetch again; report remote movement, exact ahead/behind and commit SHAs.
- [ ] Never automatically resolve divergence, force push, reset or rebase over generated-data history.
- [ ] Phase 10B stops at local candidate. main/lab changes, push and deployment need explicit approval.
- [ ] Later rollback is UI-only on current main, preserving generated-data and unrelated commits.
