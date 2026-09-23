# Babdoduk agent working rules

Read PRD.md, DESIGN_SYSTEM.md, ARCHITECTURE.md, README.md and the feature's governing docs before editing. These describe the production-scoped release candidate, not proof of deployment. Explicit owner instructions take priority.

## Git / Multi-Agent Session Protocol

- main = production; lab = integration/staging, not a shared scratch branch.
- Normal implementation uses agent/<tool>/<task> from fetched origin/lab, in a separate worktree. Controlled production candidates use release/<name> from a recorded origin/main SHA.
- ONE WORKTREE = ONE ACTIVE CODING AGENT. If another agent appears to be editing this tree, stop before editing. Separate branches alone do not isolate a shared filesystem/index.
- Start with git status, git branch -vv, git worktree list and lock/operation checks; then git fetch origin. Record branch, HEAD, origin/lab, origin/main and pre-existing changes. Never remove locks blindly.
- Existing user files, local configuration and stashes remain user-owned. Do not overwrite, stage, stash or discard them.
- Never use blind git add -A. Inspect git diff and git diff --staged, then stage explicit task-owned paths only.
- No force push, git reset --hard, git clean -fd or git checkout -- . without explicit owner authorization for that exact destructive operation.
- Commit coherent, tested session-owned work before handoff; use an Agent: Codex or Agent: Claude trailer when applicable. Do not infer historical agent identity from commit style.
- Fetch again at handoff and report starting/ending SHAs, commits, files, tests, worktree state and ahead/behind counts. Generated-data bots can advance remote branches without an active human or agent.
- If a remote moved or a push is rejected, stop automatic integration and report the new commits. Do not automatically pull, merge, rebase or bypass the rejection.
- A task branch is not permission to push directly to lab. main changes, production promotion and deployment each require explicit owner approval.
- When unfinished, report exactly what remains and a continuation prompt. Do not claim a WIP commit is a completed release.

## Implementation discipline

Use the existing static HTML/CSS/JS architecture. Shared navigation/footer styling belongs in css/site.css; inspect all eight public routes. Do not run legacy rebuild_index.py or patch_site.py without reviewing their generated diff.

Preserve keyboard access, visible focus, language switching, wrapping, reduced motion, native high-contrast scrollbars and publication/security assertions. Unknown is not a positive food or event claim. Do not weaken tests to accept a regression.

Keep all existing localStorage keys and values readable. Phase 10B preserves food-log storage and same-date browser precedence; labels are 밥도둑 공개 기록 and 이 브라우저 기록. A true two-mode accounting model is a future task.

Historical May event results remain 진행 여부 미확인. Keep the picker at mukbang.html#what. lab.html and calendar.ics are already publicly present on main: no removal, hiding, relocation or redesign in Phase 10B. noindex is not access control. Privacy/Public Surface Audit and legal documents are separate work.

## Protected boundaries

UI work does not authorize changes to supabase/, migrations/RLS, Realtime, public-feed backend/contracts, scripts/ggongbab/, Portal/Dooray collectors, Windows workers, credentials, workflows or generated data. Phase 10B must not repair/enable ggongbab-refresh.yml or edit scripts/refresh_magazine.py.

Do not run live Portal, Dooray or Supabase operations as a test. Portal detail GET remains blocked; no authentication replay, password/OTP/MFA automation or SSO bypass. Do not log or commit cookies, JSESSIONID, keys, private identifiers, mail or browser profiles.

Do not edit generated data/magazine/, data/kaist-menu/, data/ggongbab/latest.json or data/foods/ to make tests pass. data/food-log.json and data/ggongbab/manual.json are authored inputs, also outside this UI release.

Normal routes read public static snapshots only in this candidate. Local preview and fixture modes stay isolated; no frontend DB/Realtime activation is authorized. Local artifacts belong in ignored .local/. Use the loopback-only server in scripts/check_ggongbab_ui.py --serve, not an unrestricted directory server.

## Verification and handoff

For frontend work run:

- python -m pytest tests -q
- python scripts/validate_content.py
- python scripts/check_site_ui.py
- python scripts/check_ggongbab_ui.py

Use focused synthetic tests first. Keep all-upcoming defaults, saved filters, explicit food eligibility, review/expiry hiding, chronological order, Radar and featured assertions. A test clock may affect only the lab fixture route, never normal or preview routes.

Inspect 360/390 mobile, 768 tablet, 1440/1920 desktop, long titles, keyboard navigation and Korean/English states. Automated Chromium success is not evidence of real Safari, screen-reader, deployed route/cache behavior, external-service health or data freshness. Report untested areas honestly.

Phase 10B prepares a local release candidate and then stops. See docs/PHASE_10B_RELEASE.md for its exact inclusion/exclusion boundary.
