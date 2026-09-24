---
name: session-start
description: Read-only Git inspection at the start of a Babdoduk coding session. It records the branch, worktrees, stash, origin/lab and origin/main, and pre-existing changes, and confirms this is the right, unshared worktree. Use before editing in a new session or task.
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
5. Check that this is the right place to work:
   - Task work belongs on `agent/<tool>/<task>` in its own worktree; releases on `release/<name>` (see `/release-babdoduk`). Never develop on `main`, and not directly on `lab` unless the owner asked.
   - If the branch or worktree is wrong, stop and propose the right one, for example `git worktree add -b agent/claude/<task> ../Babdoduk-wt/claude-<task> origin/lab`. Do not switch the owner's checkout.
6. Stop and report instead of editing if another agent seems active:
   - recent modifications you did not make;
   - `.git/index.lock` or `.git/worktrees/*/index.lock`;
   - a merge, rebase or cherry-pick in progress;
   - the owner's own edits in files you need.

Pre-existing changes are not yours: never stage, restore, stash, commit or delete them.

Report in one compact block:
- worktree path, branch and HEAD;
- `origin/lab`, `origin/main` and ahead/behind;
- pre-existing paths and the stash count;
- "safe to proceed", or the blocker.
