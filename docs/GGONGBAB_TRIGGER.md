# Low-latency refresh trigger (Option A; code on lab only, not activated)

Owner decision 2026-09-28: **local radar → GitHub `workflow_dispatch` → the existing cloud
pipeline**. The 30-minute schedule stays as the safety net, dispatches are debounced, and the job
runs only from main. **Issuing the credential and activating it in production need one more
owner approval.** The code (`scripts/ggongbab/dispatch.py`, the workflow guard, the agent flag)
stays on lab until activation is approved.

## Why

The cloud refresh is scheduled `*/30 * * * *`, but GitHub started it far less often. Measured on
2026-09-28:
* 6 of 48 runs a day since 2026-09-25, with gaps of 159–373 min;
* `magazine-daily` slots also start 2.5–5.5 h late, and no run was cancelled.

A mail arriving at a random time waits on average 133 min for the next run (P95 300 min). Once a
run starts, collection → Luna → validation → Supabase → `latest.json` → Vercel takes about 3.5 min.
The delay is in the scheduling, not the pipeline.

## Design

```
radar registers a new candidate task
  -> scripts/ggongbab/dispatch.py request_refresh(new_candidates=True)
  -> POST /repos/joshualikaist/Babdoduk/actions/workflows/ggongbab-refresh.yml/dispatches
       {"ref": "main", "inputs": {"mode": "full", "source": "radar"}}
  -> the existing cloud job (the only writer), concurrency group babdoduk-content-refresh
```

* **Single writer.** The PC never ingests or publishes. `dooray_web_agent.py --dispatch-refresh`
  refuses `--run-pipeline`.
* **Coalescing.** The concurrency group keeps at most one running and one pending run; later
  dispatches fold into the pending one.
* **Debounce.** At most one dispatch per 5 min (`MIN_INTERVAL_SECONDS`). A candidate that arrives
  inside the window sets `pending`, and the next radar cycle sends it, so it never waits for the
  schedule. At most 60 dispatches per KST day. Network failures stay pending and are retried.
* **Main only, twice.**
  * `REF` is a constant, not a parameter.
  * The workflow's job has `if: github.ref == 'refs/heads/main'`, so a dispatch aimed at any other
    ref is skipped before any step or secret runs.
* **Traceability.** The dispatch input `source` (manual or radar) is only logged (`trigger: …`,
  passed through an environment variable, never inlined into a script).
* **Results.** Fixed codes only: `DISPATCHED`, `DISPATCH_DEBOUNCED`, `DISPATCH_NOT_CONFIGURED`,
  `DISPATCH_AUTH_FAILED`, `DISPATCH_REJECTED`, `DISPATCH_TRANSPORT_FAILED`, `DISPATCH_DAILY_CAP`,
  `DISPATCH_NOTHING_NEW`. State lives in `.local/dispatch-state.json` without any secret.

## The credential

* **Kind:** a fine-grained personal access token limited to the repository `joshualikaist/Babdoduk`.
* **Permission:** Actions: Read and write. Metadata: read is automatic. Nothing else.
* **Expiry:** 90 days or less, then rotated.
* **Storage:** Windows Credential Manager, generic credential `babdoduk/ggongbab-refresh-dispatch`
  (DPAPI, this Windows user), via
  `python scripts/dispatch_ggongbab_refresh.py --store-token`. That prompts without echo and
  checks the token's shape.
* **Where it never goes:** `.env`, the repository, logs, GitHub secrets or command lines. Avoid
  `cmdkey /pass:`, which exposes it in the process list.

What the token can do if it leaks:
* start, re-run, cancel or disable workflows;
* delete run logs.

What it cannot do:
* read secrets;
* push code;
* change settings.

The main-only guard exists only in refs that contain it, so remote branches still carrying an older
workflow file are deleted before activation. Re-running an old run executes that run's own
commit, which is bounded to existing code.

## Secrets environment

The refresh job runs in the GitHub environment `ggongbab-production`.

**Environment settings:**
* Deployment branches: `main` only; no tags.
* No required reviewer and no wait timer, so the schedule runs unattended.
* Secrets: `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `OPENAI_API_KEY`, `DOORAY_API_TOKEN`.
* Non-secret variable: `GGONGBAB_ENVIRONMENT=ggongbab-production`.

**How the job checks it:**
* The first step fails unless that variable is present, so the job can never silently fall
  back to repository-level secrets.
* A workflow file at an old tag or branch names no environment, so it receives none of these
  secrets once the repository-level copies are removed.

**Migration order:**
1. Create the environment and its secrets.
2. Release the `environment:` workflow to main.
3. Test `check` and `full` runs on main.
4. Delete the repository-level secrets.
5. Test `check` and `full` again.

**Rollback:** re-add the repository secrets and remove the `environment:` line.

**Known residual risk:** three old tags have no missing-secret guard in their workflow:
* `archive-2026-09-23-phase-0-9-original`;
* `archive-2026-09-24-phase-10b-port-snapshot`;
* `release-2026-09-24-product-refresh`.

If one of them were dispatched after step 4, it would run with no secrets and could publish an
empty free-food feed until the next scheduled run restores it. Supabase data would not be
touched. Dispatching needs a credential with Actions write access.

## Activation checklist (STOP: owner approval required)

1. Selectively promote the workflow guard (main-only `if:` and the `source` input) to main.
2. Delete stale remote branches whose workflow lacks the guard (owner; `git push origin --delete …`).
3. The owner creates the fine-grained token as above.
4. `python scripts/dispatch_ggongbab_refresh.py --store-token`, then `--status` shows `token stored: yes`.
5. `python scripts/dispatch_ggongbab_refresh.py --request` once, then confirm a `workflow_dispatch`
   run on main that logs `trigger: manual` and completes.
6. Only after step 5 succeeds, turn on the Radar's trigger:
   `python scripts\windows\ggongbab_workers.py radar-dispatch-on`.
   Until then the scheduled Radar records `DISPATCH_OFF`.
   `radar-dispatch-off` turns the trigger off again without touching the token.

**Rollback.** Run `--remove-token` and revoke the token on GitHub; the schedule keeps running.

## Not changed

The 30-minute schedule, the modes, the publisher, the permissions (`contents: write` for the
publisher only) and the secrets of `ggongbab-refresh.yml` are as before. Tests:
`tests/ggongbab/test_dispatch.py`, `tests/ggongbab/test_refresh_workflow.py`.
