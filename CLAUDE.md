@AGENTS.md

# Claude Code

- `AGENTS.md` (imported above) is the authoritative rule set. This file only adds how Claude Code works here.
- Load the long documents only when the task needs them: `PRD.md` for product scope, `DESIGN_SYSTEM.md` for visual or frontend work, `ARCHITECTURE.md` for backend or system-boundary changes, `README.md` and the governing `docs/` file for the feature you touch.
- Start an implementation session with `/session-start`, and finish it with `/handoff`.
- Product/UI work starts from the latest `origin/lab` and reaches `main` only after it is deployed on babdoduk-lab and approved (AGENTS.md "Lab-first lifecycle"). A production destination is not a reason to start from `main`.
- Before handing off meaningful code, run `/verify-babdoduk`. It knows which of the four gates a change needs and how to report a failed first run.
- Use `/ui-review` for responsive, visual and accessibility QA of pages.
- Use `/release-babdoduk` only for release or production work, and only when the owner has authorized that specific release.
- `.claude/hooks/git_guard.py` blocks force pushes, hard resets, forced cleans, blanket checkouts/restores and manual production deploys. Never work around it; ask the owner instead.
- Personal settings belong in `.claude/settings.local.json`, which is not committed.
- When the task is clear, implement rather than narrate, and report results rather than plans.
