---
name: release-babdoduk
description: Canonical Babdoduk production-release procedure. It requires an owner-approved, deployed lab candidate first, then builds a release from origin/main with only the approved commits, runs the guard and gates, and, with explicit owner authorization, pushes main, verifies production and back-syncs lab.
disable-model-invocation: true
---

# Release Babdoduk

`main` is production: every push or merge to `main` deploys https://babdoduk.vercel.app through Vercel's Git integration. This procedure never merges or pushes `main` unless the owner has explicitly authorized this specific release in the current task.

Every release follows the lab-first lifecycle in `AGENTS.md`: task → `lab` → deployed babdoduk-lab → owner approval → release candidate from `origin/main` → production → back-sync. Local tests passing is not a substitute for any step.

## 0. Lab acceptance (required gate)
Record these before building anything:

| Field | What it is |
| --- | --- |
| `LAB_TASK_SHA` | Each approved task commit to promote (normally the task branch commits, oldest first) |
| `LAB_INTEGRATION_SHA` | The `origin/lab` commit that contains them and was deployed |
| `LAB_VERCEL_DEPLOYMENT_STATUS` | The `Vercel – babdoduk-lab` status of `LAB_INTEGRATION_SHA` (`gh api repos/joshualikaist/Babdoduk/commits/<sha>/status`) |
| `LAB_URL_TESTED` | The https://babdoduk-lab.vercel.app URLs checked, with languages and widths |
| `OWNER_APPROVAL` | The owner's approval of that lab state, as given in the task |

STOP, and do not build a candidate, if:
- the lab deployment is missing or failed;
- an approved commit is not in lab: `git merge-base --is-ancestor <LAB_TASK_SHA> origin/lab` must succeed for each;
- there is no owner approval of the deployed lab state.

The only exceptions are the owner-authorized bypasses listed in `AGENTS.md` (emergency hotfix, production-only infrastructure recovery, repository-only emergency fix). Record the authorization as `LAB_BYPASS_AUTHORIZATION` in place of the lab fields, and still do the back-sync in section 8.

## 1. Start from production
- Run `/session-start`. Never build a release in the owner's checkout or in another agent's worktree.
- Run `git fetch origin --prune`, then record `BASE_MAIN` (`git rev-parse origin/main`).
- Use a dedicated worktree from the latest `origin/main`: `git worktree add --no-track -b release/<name> ../Babdoduk-wt/release-<name> origin/main`.

## 2. Promote only the approved commits
- Run `git cherry-pick -x <LAB_TASK_SHA>` for each approved commit, oldest first. Nothing else enters the candidate.
- Never `git merge lab` or `git merge origin/lab` into a release: lab also carries experiments that are not production-ready.
- Lab-only systems stay out: the public projection/Realtime client, heartbeat, the Portal LIST poller and the Windows workers.
- Resolve conflicts by hand and explain each resolution in the commit message. If a resolution changes user-visible behavior compared with what was approved on lab, STOP: that change goes back through lab first.
- Commit release-only fixes by explicit path, with the `Agent:` trailer, and only if they change no behavior (for example a test fixture adjusted to main's data).

## 3. Guard (every command below must print nothing)
```
git diff --name-only BASE_MAIN...HEAD | grep -E '^(data/|supabase/|\.github/workflows/|scripts/ggongbab/|scripts/windows/)'
git diff BASE_MAIN...HEAD -- '*.html' 'js/*.js' | grep '^+' | grep -i -E 'supabase|createClient|new WebSocket|EventSource\(|ggongbab-public-(feed|config)'
git diff --name-only BASE_MAIN HEAD -- scripts/dooray_web_agent.py scripts/portal_web_agent.py scripts/run_ggongbab_agent.cmd requirements-ggongbab.txt
```
These paths are protected unless the task explicitly authorizes one of them, and a UI release adds no browser backend. If any command prints something, STOP and do not push.

## 4. Gates
On a clean release HEAD, run all five gates from `/verify-babdoduk` one at a time, plus the real-font smoke for layout or copy changes. Keep the first-run results.

## 5. Push the release branch
- `git push -u origin release/<name>`. Push normally; a non-fast-forward rejection means STOP.
- Read the commit's checks, the Vercel Preview for the `babdoduk` and `babdoduk-lab` projects: `gh api repos/joshualikaist/Babdoduk/commits/<sha>/status`.
- Previews sit behind Vercel Authentication. Do not bypass it, and never deploy with the Vercel CLI.

## 6. Production merge (only with explicit owner authorization for this release)
1. Run `git fetch origin --prune`. If `origin/main` has moved since `BASE_MAIN`, list the new commits:
   - `babdoduk-content-bot` with data-only paths: integrate from the newest `origin/main`;
   - any human or source commit: STOP and report.
2. Build the candidate in a fresh integration worktree based on the newest main:
   `git worktree add --detach ../Babdoduk-wt/prod-integration origin/main`, then `git merge --no-ff origin/release/<name> -m "Merge release/<name>"`.
3. Run all gates and the guard again on this exact merge candidate. Release-branch results do not count for it.
4. Record `PRE_RELEASE_MAIN_SHA` (the `origin/main` you merged into) and the merge SHA. Fetch once more; then run `git push origin HEAD:main` as a normal push, never with force. If it is rejected, fetch, re-check the new commits and rebuild the candidate.

## 7. Verify production
- `git fetch origin`, and confirm `origin/main` equals the merge SHA.
- Wait for the commit's `Vercel – babdoduk` status to succeed.
- Smoke-test https://babdoduk.vercel.app read-only: pages load, navigation works, the changed features behave as they did on lab, there are no console exceptions and no unexpected supabase/Realtime requests.

## 8. Back-sync lab (required; the release is not complete without it)
- In a fresh worktree from the latest `origin/lab`, run a normal merge of the latest `origin/main` (never rebase, never force). Keep intentional lab-only experiments; resolve each conflict file by file.
- Run the gates, push `lab` normally, and wait for the `Vercel – babdoduk-lab` status of the new `lab` commit to succeed.
- Confirm the drift check prints nothing: `git log --format='%h %an %s' origin/lab..origin/main | grep -v babdoduk-content-bot`.
- Record `BACK_SYNC_LAB_SHA`.

## 9. Rollback boundary
- Keep the release branch after merging.
- For a severe regression, revert the merge (`git revert -m 1 <merge-sha>` in a worktree, then a normal push). Never reset `main`. Generated-data commits made after the merge stay. Back-sync the revert into `lab` too.

## Report
- `LAB_TASK_SHA`, `LAB_INTEGRATION_SHA`, `LAB_VERCEL_DEPLOYMENT_STATUS`, `LAB_URL_TESTED` and `OWNER_APPROVAL`, or `LAB_BYPASS_AUTHORIZATION`.
- `BASE_MAIN`, `PRE_RELEASE_MAIN_SHA`, the release HEAD and its remote SHA.
- The commits included, with provenance (the `-x` lines).
- The guard result and the gates' first-run results.
- Remote movement and the Preview and production deployment states.
- The merge SHA and the push result.
- Smoke results and what was not tested.
- `BACK_SYNC_LAB_SHA`, its babdoduk-lab deployment status and the empty drift check.
- The verdict, naming any blocker.
