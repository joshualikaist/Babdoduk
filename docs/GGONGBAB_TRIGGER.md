# Low-latency refresh trigger (Option A)

Owner decision 2026-09-28: **local radar → GitHub `workflow_dispatch` → the existing cloud
pipeline**. The 30-minute schedule stays as the safety net, dispatches are debounced, and the job
runs only from main. **Issuing the credential and activating it in production need one more
owner approval.** The code (`scripts/ggongbab/dispatch.py`, the workflow guard, the agent flag)
stays on lab until activation is approved.

**2026-11-03: the owner approved activation on the Linux operations PC** ("자동 갱신 작업 시작하자"),
after scheduled runs left 4–9 h gaps and a confirmed tip waited half a day. The main-only guard and the
`source` input were already on main. Three senders share one switch and one debounce state
(`.local/dispatch-state.json`):

| Sender | When it asks | Code |
| --- | --- | --- |
| Dooray Radar | a cycle registered a new candidate task | `scripts/windows/ggongbab_workers.py radar` |
| Instagram radar | a cycle handed a confirmed post over (`bridge`) | `ggongbab/instagram/radar.py` |
| Reader tips | the owner's ✅ handed a tip over (checked every ~25 s between cycles) | `ggongbab/tips.py` → the radar |

A quiet call (`new_candidates=False`) only sends a request that the 5-minute debounce held back.

**2026-11-03 audit ("지금 많은 부분을 서로서로 놓치고 있는거 같아"; owner approved the fixes):**

* **Keep-alive.** GitHub still ran the schedule only 4–6 times a day, and nothing asked for a run after an
  owner SQL edit, a manual.json change or a held event. The Instagram radar's quiet call (every ~25 s)
  now passes `keepalive=True`: when no dispatch went out for 30 min (`KEEPALIVE_SECONDS`) it asks for one.
  `DAILY_CAP` is 96 (48 keep-alive runs plus candidates).
* **"갱신" on Telegram.** A message that is only 갱신 (새로고침, refresh) asks for a run at once and the bot
  says what happened (requested, debounced, switch off, cap).
* **No skipped requests.** The quiet call runs in a `finally`, so a Telegram failure no longer skips a
  debounced request or a ✅ tip. A request that cannot go out (token rejected, not configured, cap, or
  20 transport failures in a row) is told to the owner through the bot, at most every 6 h per cause.
* **Held events.** Each radar cycle asks the owner about upcoming free-food events that the pipeline
  holds for review (`ggongbab/held.py`); ✅ publishes the row and asks for a refresh, ❌ rejects it.
* Measured 2026-11-03: a whole run takes 9–13 min (collection re-reads up to 500 Dooray tasks), not the
  3.5 min of 2026-09-28 below.

## Why

The cloud refresh was scheduled `*/30 * * * *`, but GitHub started it far less often. Since 2026-10-12 it
is `7,37 * * * *`: the same rate, off the hour and the half hour, where scheduled runs crowd. Measured on
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
  schedule. At most 96 dispatches per KST day (60 until 2026-11-03). Network failures stay pending and are retried.
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
* **Storage:** the operator's credential store, target `babdoduk/ggongbab-refresh-dispatch`
  (`scripts/ggongbab/ops_credentials.py`):
  * Linux (the operations PC since 2026-10-17): one file under `~/.config/babdoduk/credentials/`
    (directory 0700, file 0600, outside every checkout). A file others could read is refused, as if
    nothing were stored.
  * Windows: Credential Manager, generic credential (DPAPI, this Windows user).

  The owner stores it with `python scripts/dispatch_ggongbab_refresh.py --store-token`, which prompts
  without echo and checks the token's shape. Agents never ask for, read or print it.
* **Where it never goes:** `.env`, the repository, logs, state files, GitHub secrets or command lines.
  Avoid `cmdkey /pass:` on Windows, which exposes it in the process list.

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
6. Only after step 5 succeeds, turn on the trigger for the Dooray Radar, the Instagram radar and the
   tips at once: `python scripts/windows/ggongbab_workers.py radar-dispatch-on`.
   Until then the radars record `DISPATCH_OFF`.
   `radar-dispatch-off` turns the trigger off again without touching the token.

On the Linux operations PC the commands run from `~/Babdoduk-ops` with `.venv/bin/python`, and the
Instagram radar picks the switch up on its next request (no restart). The radars must run code that
contains this sender (`systemctl --user restart babdoduk-ig-radar.service` after an update).

**Rollback.** Run `--remove-token` and revoke the token on GitHub; the schedule keeps running.

## Not changed

The 30-minute schedule, the modes, the publisher, the permissions (`contents: write` for the
publisher only) and the secrets of `ggongbab-refresh.yml` are as before. Tests:
`tests/ggongbab/test_dispatch.py`, `tests/ggongbab/test_refresh_workflow.py`.
