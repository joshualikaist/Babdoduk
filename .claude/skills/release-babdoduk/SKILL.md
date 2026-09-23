---
name: release-babdoduk
description: Canonical Babdoduk production-release procedure. It covers the release worktree from origin/main, the protected-path guard, gates, pushing the release branch, and, only with explicit owner authorization, the merge to main, production checks and the rollback boundary.
disable-model-invocation: true
---

# Release Babdoduk

`main` is production: every push or merge to `main` deploys https://babdoduk.vercel.app through Vercel's Git integration. This procedure never merges or pushes `main` unless the owner has explicitly authorized this specific release in the current task.

## 1. Start from production
- Run `/session-start`. Never build a release in the owner's checkout or in another agent's worktree.
- Run `git fetch origin --prune`, then record `BASE_MAIN` (`git rev-parse origin/main`).
- Use a dedicated worktree: `git worktree add --no-track -b release/<name> ../Babdoduk-wt/release-<name> origin/main`, or reuse a clean worktree that already holds this release.

## 2. Bring in only approved changes
- Run `git cherry-pick -x <sha>` for each approved commit, oldest first. Resolve conflicts by hand and explain each manual resolution in the commit message.
- Lab-only systems stay out of a UI release: the public projection/Realtime client, heartbeat, the Portal LIST poller and the Windows workers.
- Commit release fixes by explicit path, with the `Agent:` trailer.

## 3. Guard (every command below must print nothing)
```
git diff --name-only BASE_MAIN...HEAD | grep -E '^(data/|supabase/|\.github/workflows/|scripts/ggongbab/|scripts/windows/)'
git diff BASE_MAIN...HEAD -- '*.html' 'js/*.js' | grep '^+' | grep -i -E 'supabase|createClient|new WebSocket|EventSource\(|ggongbab-public-(feed|config)'
git diff --name-only BASE_MAIN HEAD -- scripts/dooray_web_agent.py scripts/portal_web_agent.py scripts/run_ggongbab_agent.cmd requirements-ggongbab.txt
```
These paths are protected unless the task explicitly authorizes one of them, and a UI release adds no browser backend. If any command prints something, STOP and do not push.

## 4. Gates
On a clean release HEAD, run all four gates from `/verify-babdoduk`, one at a time. Keep the first-run results.

## 5. Push the release branch
- `git push -u origin release/<name>`. Push normally; a non-fast-forward rejection means STOP.
- Read the commit's checks, the Vercel Preview for the `babdoduk` and `babdoduk-lab` projects: `curl -s https://api.github.com/repos/joshualikaist/Babdoduk/commits/<sha>/status`.
- Previews sit behind Vercel Authentication. Do not bypass it, and never deploy with the Vercel CLI.

## 6. Production merge (only with explicit owner authorization for this release)
1. Run `git fetch origin --prune`. If `origin/main` has moved since `BASE_MAIN`, list the new commits:
   - `babdoduk-content-bot` with data-only paths: integrate from the newest `origin/main`;
   - any human or source commit: STOP and report.
2. Build the candidate in a fresh integration worktree based on the newest main:
   `git worktree add --detach ../Babdoduk-wt/prod-integration origin/main`, then `git merge --no-ff origin/release/<name> -m "Merge release/<name>"`.
3. Run all four gates and the guard again on this exact merge candidate. Release-branch results do not count for it.
4. Record `PRE_RELEASE_MAIN_SHA` (the `origin/main` you merged into) and the merge SHA. Then run `git push origin HEAD:main` as a normal push, never with force. If it is rejected, fetch, re-check the new commits and rebuild the candidate.
5. Verify production:
   - `git fetch origin`, and confirm `origin/main` equals the merge SHA;
   - wait for the commit's `Vercel – babdoduk` status to succeed;
   - smoke-test https://babdoduk.vercel.app read-only: pages load, navigation works, the changed features behave, there are no console exceptions and no unexpected supabase/Realtime requests.

## 7. Rollback boundary
- Keep the release branch after merging.
- For a severe regression, revert the merge (`git revert -m 1 <merge-sha>` in a worktree, then a normal push). Never reset `main`. Generated-data commits made after the merge stay.

## Report
- `BASE_MAIN`, `PRE_RELEASE_MAIN_SHA`, the release HEAD and its remote SHA.
- The commits included, with provenance.
- The guard result and the gates' first-run results.
- Remote movement and the Preview and production deployment states.
- The merge SHA and the push result.
- Smoke results and what was not tested.
- The verdict, naming any blocker.
