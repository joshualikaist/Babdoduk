# Branches and controlled production promotion

## Approved Git model

| Branch | Role |
| --- | --- |
| main | Production |
| lab | Integration/staging, never a shared scratch branch |
| agent/<tool>/<task> | Isolated implementation work |
| release/<name> | Reviewed production candidate |

One active agent per worktree. Separate branches in the same directory do not isolate edits or the index. Normal tasks start from fetched origin/lab; a controlled release starts from a pinned fetched origin/main. Do not switch another agent's branch, erase their changes or remove locks.

Read AGENTS.md for mandatory start/end checks. Fetch does not mean pull/merge permission. Record HEAD, remote SHAs, dirty files and stashes before mutation. Stage explicit owned paths only; coherent commits should identify the agent with a trailer.

## Phase 10B candidate

release/product-refresh-2026-09 selectively ports approved UI/docs/tests onto main, not the whole lab history. See PHASE_10B_RELEASE.md. Realtime, public-feed backend, collectors, workers, migrations, generated data and workflow changes remain excluded.

Preparing/committing this local candidate does not authorize push, merge into main/lab or deployment. A remote movement or non-fast-forward rejection requires inspection, never force push or automatic rebase over generated-data commits.

## Hosting and public surfaces

Repository policy associates main with the babdoduk Vercel project (babdoduk.vercel.app) and lab with babdoduk-lab (babdoduk-lab.vercel.app). These are documented mappings, not a live deployment check. Verify linked project, deployed revision and owner authority before deployment.

lab.html, lab-ggongbab.html and calendar.ics already exist in main. A lab filename or noindex does not make content private. Phase 10B retains their public presence; a later Privacy / Public Surface Audit decides exposure changes.

## Generated-data movement

magazine-daily.yml declares magazine at 10:00 KST and cafeteria at 06:00, 10:30 and 16:30 KST. ggongbab-refresh.yml declares every 30 minutes, but is reported broken; this release must not fix or enable it.

publish_generated.py mirrors only allowlisted generated magazine/menu/free-food output to lab/main, not feature code or authored manual inputs. Bot commits can move both branches during a coding session. Workflow concurrency coordinates participating workflows, not agents.

Do not run the publisher as UI QA or manually edit/revert/bundle generated data into this release.

## Promotion and rollback after separate approval

1. Fetch and review current main/lab movement without automatic integration.
2. Review exact candidate diff, protected-path equality and all test gates.
3. Obtain owner approval for the intended merge/push/deployment and target project.
4. Verify deployed SHA, routes/404, cache and snapshot publication dates afterward.
5. If rollback is authorized, revert only this release's UI/docs/test commits on the current production line. Do not reset main or revert generated-data/unrelated commits. Hosting rollback may also restore older JSON; inspect that separately.

No deployment commands are part of Phase 10B.
