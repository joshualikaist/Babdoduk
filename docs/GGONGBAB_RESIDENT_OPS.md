# Phase 2C-OPS: Windows resident operations (lab)

## 1. What this worker does

The Portal worker reuses a manually authenticated session and polls the pinned
Portal recent-post LIST every 60 seconds. It keeps the existing baseline, dedup
ledger and private Stage A pending data. It sends the existing operational
`agent_heartbeats` row under `portal-list-poller`. It creates no confirmed food
events, public feed rows, Realtime events or end-user push messages.

The installer registers one Task Scheduler task, `Babdoduk-Portal-Worker`.
It launches a hidden `pythonw.exe` watchdog **30 seconds after the installing
user logs on**, using Interactive logon and Limited privileges. No password,
administrator elevation, boot service or open CMD window is required. Enterprise
policy may deny user task registration; the script reports failure, not an
automatic elevation attempt. Locking the screen does not log the user off.

The watchdog inspects state every 15 seconds and owns a hidden child worker.
Task Scheduler's IgnoreNew setting, a watchdog OS lock, and the original
`.local/portal-list.lock` prevent concurrent supervisors/pollers. The same lock
also protects against a separately started `portal_web_agent.py --poll-list`.
Neither stale lock filenames nor process restart resets the baseline.

This is not a public server. No site/browser connects to this PC. Collection and
heartbeats use outbound HTTPS. Chrome CDP is **local loopback only**, Portal 9223
and Dooray 9222; these are not public listening services and must not be exposed
through a firewall/router tunnel.

## 2. What happens if my PC is off?

| Component | PC OFF |
|---|---|
| Vercel site | Continues independently |
| Supabase | Continues independently |
| GitHub Actions | Continues independently |
| Already deployed latest.json/public feed | Remains available |
| Portal 60-second detection | Stops |
| Local authenticated browser agents | Stop |

Cloud availability still depends on the providers and their configuration, not on
the Windows worker. The PC cannot collect while powered off, asleep or hibernating.

## 3. Install

From the repository root, on `lab`, with normal-user PowerShell:

```powershell
python -m pip install -r requirements-ggongbab.txt
powershell -NoProfile -File scripts\windows\install_ggongbab_tasks.ps1
# For a specific virtual environment:
powershell -NoProfile -File scripts\windows\install_ggongbab_tasks.ps1 -PythonExe .venv\Scripts\python.exe
```

Installed Google Chrome and Playwright's Python package are required. The worker
uses installed Chrome, not a newly downloaded browser. Existing backend Supabase
configuration and heartbeat migration 003 must already be available. The installer
checks imports/config presence locally, without contacting Portal/Supabase/OpenAI.
It does not apply migrations, collect data, open Chrome, or start the task now.
The approved Python executable path is stored in `.local/ops-python.txt`, with no
secret values. Keep the repository and Python environment at those paths.

The task runs at next user logon. Use Start below for immediate operation. If local
PowerShell policy blocks unsigned scripts, review that policy with the machine
administrator; these scripts do not silently change it or request elevation.
An existing task with the same name is not overwritten. Remove the known task
first to reinstall; removal checks its action, repository, interpreter and owner.

## 4. Start

```cmd
scripts\windows\start_ggongbab_workers.cmd
```

This checks the lab checkout/environment, explicitly acknowledges the previous
manual-action latch and restart budget, and starts the task. Starting while a
poller already holds its lock does not spawn a second poller. After a human-action
failure, fix the cause **before** running Start. Logon/Task Scheduler restarts do
not clear a saved auth/UI/manual latch or reset the retry budget.

Worker startup takes the existing poller lock before inspecting the ledger and
Chrome. If no listener **and no matching dedicated browser process** exists,
it starts only `.local/portal-browser-profile` on 9223, using existing session
restore behavior and the Portal landing page. It then verifies ownership again
and performs the normal in-memory session handoff and LIST verification.
SSO/MFA prompts are for a human. No authentication endpoint is replayed.

An ambiguous owner or inaccessible process inventory is not classified as absence.
It fails closed. A dedicated browser process with no listener is classified as
stale, and requires the explicit recovery command. Status never assumes an open
port is proof of a valid/authenticated Chrome session.

## 5. Stop

```cmd
scripts\windows\stop_ggongbab_workers.cmd
```

Stop persists `enabled=false`. The managed worker checks it between requests and
at most every five seconds during waits; the watchdog also exits. The command
waits up to 60 seconds for both locks to release. It does not terminate arbitrary
Python/Chrome processes. A blocked network call can delay stopping; a timeout is
reported rather than forcing termination. A separately started manual poller
does not use this control file: stop that process yourself before recovery.

Chrome stays open. Profile, cookies, baseline and pending are retained. Disabled
state survives logon until the operator explicitly starts workers again.

## 6. Status

```cmd
scripts\windows\status_ggongbab_workers.cmd
```

Status reports the poller lock, 9223's verified/missing/stale/unverified state,
safe reason, and seconds since the last successfully written healthy heartbeat.
It does not query any cloud service or display process/account/source identifiers,
environment variables, cookie material, notice titles or response bodies.
Dooray is shown as not managed, port 9222 not probed; no Dooray browser is started.

The watchdog uses the **existing heartbeat emission path**. After the
`ggongbab_record_heartbeat` RPC succeeds, it mirrors the confirmed success time
locally. A failed write does not advance that time. This is not an independent
remote heartbeat reader and cannot prove an external writer has not subsequently
changed the cloud row. A local watchdog also cannot alert while this PC is off.

Thresholds use **last successful scan**, not merely the most recent attempt:

| Age/state | Operator status |
|---|---|
| Success age <= 180 seconds | Healthy |
| Success age > 180 seconds | Warning |
| Success age > 600 seconds, or no success recorded | Critical |
| auth_required, ui_changed, ownership/state/configuration problem | Immediate operator action |
| Worker missing or Chrome absent | Independently reported; never interpreted as profile corruption |

If Chrome disappears while the already handed-off HTTP session still works,
the watchdog reports it but does not interrupt that useful session. Chrome is
started again at the next worker bootstrap, or by the recovery command. Browser
absence is not evidence that the HTTP session expired.

## 7. Portal manual login recovery

```cmd
scripts\windows\stop_ggongbab_workers.cmd
python scripts\portal_web_agent.py --setup --cdp
scripts\windows\start_ggongbab_workers.cmd
```

Manually complete SSO/MFA only when prompted. Existing sessions may be reused.
An expired session, missing/ambiguous cookie or Portal context, redirect requiring
review, or changed LIST schema stops automatic retries. Fix/review first, then
Start explicitly. Setup only confirms session readiness; it is not a replay
contract verification or a forced fresh login.

## 8. Browser recovery

```cmd
scripts\windows\recover_portal_browser.cmd
```

This disables polling and waits for its lock, inspects only the dedicated Portal
Chrome, and makes one recovery/setup attempt. A known CDP attach timeout or a
matching non-listening stale process permits targeted restart. A healthy verified
browser is reused; an absent browser is started. Immediately before stopping a
stale process, Windows rechecks its exact command line, PID creation time and any
9223 owner. An unrelated/reused PID or ambiguous owner aborts. No `taskkill /IM`,
profile deletion, cookie clearing or state reset is used. Complete manual login
if prompted, then run Start; recovery itself does not enter a login loop.

Automatic CDP attach recovery is limited to one verified dedicated-browser restart
per failure series. An unresponsive but live poller is reported for human review,
not killed while it might be writing its ledger. Only the targeted recovery path
may stop the verified dedicated Chrome; normal Stop leaves it running.

## 9. Sleep, hibernate and network behavior

PC on + logged in allows collection. Locked sessions normally continue if Windows
keeps the processes running. Sleep/hibernate pauses collection; shutdown/logoff
ends it. No WakeToRun or wake timer is installed. On wake, surviving tasks continue
and re-evaluate elapsed times. If the worker died, the watchdog can restart it;
after a full restart, logon is required. A usable Portal session is still required.

Network/transport problems back off. The worker permits five consecutive failed
scans with exponential delays (120, 240, 480, 900 seconds, and server Retry-After
when longer). It then exits. The watchdog allows five additional starts after
the initial start, separated by 60/120/240/480/900 seconds or a longer Retry-After.
Budgets persist across watchdog/logon restarts. Ten minutes of continuously running
worker time with a recent successful scan replenishes the restart budget.
Exhaustion requires operator Start; there is no unlimited restart loop.

Observed recovery (`new=4`, one candidate, pending increasing from 1 to 2) is evidence
of **bounded** catch-up only. Pagination and the saved overlap window cannot
guarantee recovery of all notices after arbitrarily long downtime.

## 10. Uninstall

```powershell
powershell -NoProfile -File scripts\windows\remove_ggongbab_tasks.ps1
```

It cooperatively stops the managed processes and unregisters only the verified
Babdoduk task. A timeout or ownership mismatch aborts removal. It preserves all
browser and Portal data, operational state and logs. It does not remove unrelated
or older Dooray tasks; review those separately in Task Scheduler.

## 11. Troubleshooting / restart matrix

| Fixed reason | Action |
|---|---|
| WORKER_EXITED | Bounded watchdog restart with backoff |
| PORTAL_LIST_CONNECT_TIMEOUT / READ_TIMEOUT / CONNECTION_ERROR / TLS_ERROR / CHUNK_READ_ERROR / TRANSPORT_UNAVAILABLE | Bounded worker retries, then bounded watchdog restarts; TLS checks stay enabled |
| PORTAL_HEARTBEAT_WRITE_FAILED | Separate heartbeat failure; bounded restart, no false healthy confirmation |
| PORTAL_CDP_ATTACH_TIMEOUT | One bounded retry with verified dedicated-browser recovery, then manual |
| PORTAL_RESIDENT_OWNER_UNVERIFIED | Inspect absence vs stale vs ambiguous ownership; no automatic kill of an unverified process |
| PORTAL_LIST_AUTH_REQUIRED / REDIRECT_REQUIRES_MANUAL_REVIEW | Manual setup/review, no automatic login |
| PORTAL_SESSION_COOKIE_MISSING_OR_AMBIGUOUS / COOKIE_UNUSABLE / CONTEXT_MISSING_OR_AMBIGUOUS / SESSION_HANDOFF_FAILED | Manual inspection/setup |
| PORTAL_UI_CHANGED | Stop for contract review; detail access remains blocked |
| PORTAL_LIST_STATE_UNAVAILABLE / OPS_STATE_UNAVAILABLE | Stop; inspect storage, never reset the baseline |
| PORTAL_LIST_SCAN_INCOMPLETE | Stop for catch-up/window review; never advance an incomplete checkpoint |
| OPS_CONFIGURATION_REQUIRED | Fix backend configuration/Python/repository, then Start |
| OPS_RETRY_EXHAUSTED / OPS_WORKER_UNRESPONSIVE | Operator intervention; never a tight retry/kill loop |

CDP timeout and owner failure keep their fixed reason in a `collector_error`
heartbeat, distinct from a confirmed auth-required failure. The process exit
remains compatible with the existing Portal command conventions.

## Dooray and cloud responsibility audit

`collectors/dooray.py` reads collection-project tasks, task bodies and optional
attachments via Dooray's project API. It cannot scan the authenticated web mail
inbox. Tasks may already be produced by Dooray's configured mail classification.
The local Dooray browser on **9222** uniquely scans mail and creates candidate
project tasks; it is useful for missing classification coverage, recovery or
operator-requested backfill. Verified read-state rules still protect mail bodies.

The new installer **does not schedule Dooray** and does not add an ingest pipeline
to Portal. Audit any pre-existing `run_ggongbab_agent.cmd` task. If automatic mail
classification already covers the inbox, a second continuously scheduled local
mail bridge is unnecessary. If coverage is missing, decide which bridge owns that
mail population before scheduling it; do not blindly run both on the same mail.
Prefer one canonical pipeline writer (the cloud job), using local pipeline runs
only as deliberate operator recovery, not concurrent scheduled ingestion.

Existing safeguards: local mail state plus task `mail_key` avoids repeated local
task registration; canonical `(source_id, external_id)`, content hashes and event
matching avoid normal replay duplication. Unmarked tasks independently created by
another classification path can have different IDs; heuristic event matching is
**not** a database-level guarantee against concurrent cross-process insert races.
This phase introduces no second automatic path and does not claim to solve that
pre-existing race. Do not schedule the legacy local `--run-pipeline` simultaneously
with cloud ingest. The legacy launcher retains its behavior but routes logs through
a bounded operational-only wrapper; detailed child output is not persisted.

`.github/workflows/ggongbab-refresh.yml` schedules every 30 minutes from the
default branch. Its Dooray/project and public/manual collection, AI parsing and
static JSON generation continue independently of this PC, subject to secrets and
provider availability. Phase 2A public projection sync and these ops scripts are
on **lab**; the default-branch cron acquires them only after an explicitly approved
promotion. Migration 004 remains a separate manual prerequisite for Phase 2A.
No public feed security model or migration is changed here.

## Logs, alerts and test boundary

New worker/watchdog logs, the Portal agent file log and the legacy local Dooray
file log use rotation: **5 MiB active + three backups**, about 20 MiB per logger.
Only fixed operational codes are persisted by these entry points. Raw exception
text/stdout/stderr, notice/mail content, identifiers and secrets are not saved.
Existing historical log entries are not retroactively scrubbed; an oversized
legacy file is archived intact and ages out through rotation. Do not publish it.

`.local/ops-alert.json` is the future operator notifier interface: component,
severity, action, fixed reason, success age, observed timestamp and worker-running
flag. No third-party notifier is installed or message sent. A future external
monitor can also observe the existing cloud `agent_heartbeats` row while this PC
is offline. This is operator alerting, not end-user Web Push.

`.local/ops-control.json`, `ops-watchdog.json` and `ops-portal.json` contain only
operational settings/budgets/timestamps/reasons. Corruption fails closed. Do not
delete `portal-list-state.json` to fix an ops error; it is a different file.
The Stage A pending ledger remains local/private and is never uploaded by ops.

Automated verification uses fakes, temporary state, static task/PowerShell syntax
checks and the existing Portal LIST gate tests. It does not register tasks, start
or stop real Chrome, contact live Portal/Dooray/Supabase/OpenAI, apply migrations,
or deploy. Actual Windows logon/sleep and interactive SSO acceptance remain an
operator test after installation. Task Scheduler details follow Microsoft's
[principal](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtaskprincipal)
and [settings](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasksettingsset) documentation.
