---
name: handoff
description: Finish a Babdoduk coding session safely. It classifies changes, stages explicit paths only, runs the right checks, commits with an Agent trailer when asked, re-fetches, and reports SHAs, remote movement, tests and dirty state.
---

# Handoff

Use this at the end of a coding session, or when the owner asks for a commit.

1. See everything that changed:
   `git status --short` · `git diff --stat` · `git diff` · `git diff --staged`
2. Classify every path:
   - session-owned;
   - owner/pre-existing (compare with the `/session-start` record);
   - generated data (`data/magazine/`, `data/kaist-menu/`, `data/ggongbab/latest.json`, `data/foods/`);
   - unrelated.
   Only session-owned paths may be staged.
3. Verify with `/verify-babdoduk` for the change type, and keep the exact first-run results, failures included.
4. Commit only coherent, complete work, and only when the task asks for a commit:
   - `git add -- <session-owned paths...>`. Never `git add -A`, `git add .` or `git commit -a` while anything else is dirty.
   - Run `git diff --cached --check` and review `git diff --cached --stat`.
   - Write a subject that says what changed and a body that says why, then the `Agent: Claude` trailer and any co-author line the session requires.
   - Incomplete work is not committed as finished. A WIP commit needs owner permission and a `WIP:` subject.
5. Run `git fetch origin --prune` and compare with the session-start record: did `origin/lab` or `origin/main` move? Classify each new commit by author and paths. `babdoduk-content-bot` touching only `data/…` is expected movement.
6. Push only your task branch, only when the task authorizes it, and never with force. A non-fast-forward rejection means stop and report.
7. Report:
   - starting SHA → ending SHA, and the commits created (SHA and subject);
   - files changed and the user-visible result;
   - tests with exact counts, and first-run failures with evidence;
   - remote movement and ahead/behind (`git rev-list --left-right --count HEAD...origin/lab`);
   - final `git status --short` and whose each dirty path is;
   - what was not tested, open risks and owner decisions.

If the session is interrupted, leave a continuation note: the current SHA, uncommitted paths, the completed and next steps, open decisions, and the commands to resume.
