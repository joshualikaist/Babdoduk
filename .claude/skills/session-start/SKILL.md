---
name: session-start
description: Read-only Git inspection at the start of a Babdoduk coding session. It records the branch, worktrees, stash, origin/lab and origin/main, pre-existing changes and lab drift, and confirms the task starts from origin/lab in its own worktree. Use before editing in a new session or task.
---

# Session start

This procedure only observes and reports. Never stash, reset, clean, restore or switch branches here.

1. Identify where you are:
   `git rev-parse --show-toplevel` · `git branch --show-current` · `git status --short --branch`
2. Map the surroundings:
   `git worktree list` · `git branch -vv` · `git stash list`
3. Refresh remote refs (this does not touch any working tree): `git fetch origin --prune`
4. Record these for the handoff:
   - starting `HEAD` (`git rev-parse HEAD`)
   - `origin/lab` and `origin/main` (`git rev-parse origin/lab origin/main`)
   - ahead/behind against the upstream when there is one (`git rev-list --left-right --count HEAD...@{u}`)
   - every pre-existing modified, staged or untracked path, and the stash list
5. Check lab drift (lab-first lifecycle in `AGENTS.md`):
   `git log --format='%h %an %s' origin/lab..origin/main | grep -v babdoduk-content-bot`
   If this prints anything, production has source commits that staging lacks, so babdoduk-lab no longer previews production. Report "LAB BEHIND PRODUCTION" with the commits, and back-sync `origin/main` into `lab` (or have the owner decide) before starting product work.
6. Check that this is the right place to work:
   - Product, UI, frontend, copy and navigation tasks start from the latest `origin/lab`, even when the result is meant for production:
     `git worktree add --no-track -b agent/<tool>/<task> ../Babdoduk-wt/<task> origin/lab`
   - Start from `origin/main` only for an owner-authorized bypass listed in `AGENTS.md` (emergency hotfix, production-only infrastructure recovery, repository-only emergency fix), or for a release candidate (`/release-babdoduk`). Record the authorization.
   - Never develop on `main`, and not directly on `lab` unless the owner asked.
   - If the branch or worktree is wrong, stop and propose the right one. Do not switch the owner's checkout.
7. Stop and report instead of editing if another agent seems active:
   - recent modifications you did not make;
   - `.git/index.lock` or `.git/worktrees/*/index.lock`;
   - a merge, rebase or cherry-pick in progress;
   - the owner's own edits in files you need.

Pre-existing changes are not yours: never stage, restore, stash, commit or delete them.

Report in one compact block:
- worktree path, branch and HEAD;
- `origin/lab`, `origin/main` and ahead/behind;
- the lab drift check result (empty, or the production commits lab lacks);
- the task base (`origin/lab`, or the recorded bypass authorization);
- pre-existing paths and the stash count;
- "safe to proceed", or the blocker.
