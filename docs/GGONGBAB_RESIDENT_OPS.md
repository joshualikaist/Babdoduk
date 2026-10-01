# Phase 2C-OPS: Windows resident operations (lab)

## 0. Babdoduk Ops Chrome: the one browser to keep open

```text
Babdoduk Ops Chrome   (one window, minimized is fine)
  [ KAIST Portal ] [ Dooray 받은메일함 ]
  profile .local\ops-browser-profile   CDP 127.0.0.1:9224 (loopback only)
        |-- Babdoduk-Portal-Worker   (LIST-only polling, its own task and failure domain)
        `-- Babdoduk-Dooray-Radar    (list-level, unread-safe, its own task and failure domain)
```

The two workers stay separate processes and Task Scheduler tasks: a Portal failure never stops
the Radar and a Radar failure never stops Portal. Only the browser is shared. It is a dedicated
profile, never the owner's own Chrome profile, and its debugging port is bound to 127.0.0.1 only.

All commands run from the operations checkout (`C:\Users\joshu\Babdoduk-ops`).

| Need | Command |
|---|---|
| Open / reuse the Ops Chrome | `scripts\windows\start_ops_browser.cmd` |
| Is it running, are both tabs there? | `scripts\windows\status_ops_browser.cmd` (or `status_ggongbab_workers.cmd` for everything) |
| A tab asks for SSO | Log in **by hand** in that tab: Portal SSO in the Portal tab; Dooray SSO, then 메일 → 받은메일함 in the Dooray tab. Then start the stopped worker (below). |
| Browser stuck / stale | `scripts\windows\recover_ops_browser.cmd` (pauses both workers, then targeted recovery) |
| Stop the workers | `scripts\windows\stop_ggongbab_workers.cmd` and `powershell -NoProfile -File scripts\windows\radar_tasks.ps1 -Action Stop` |
| Start the workers | `scripts\windows\start_ggongbab_workers.cmd` and `powershell -NoProfile -File scripts\windows\radar_tasks.ps1 -Action Start` |
| Roll back to two browsers | section 14 |

Status shows only `running / missing / stale / unverified` for the browser and, per tab,
`present` (Dooray: `present (inbox)`), `SSO login page` or `absent`. Before login the Portal
tab sits on the KAIST SSO page; while any SSO page is open, Start and Recover open no tab, so a
login in progress never gets a duplicate. Status never shows an account, cookie, URL, notice
title or mail subject.

Do **not** use `dooray_web_agent.py --setup` to log in again: it rewrites the calibrated
`mail_url` and marks the Dooray contract unverified. `portal_web_agent.py --setup --cdp` is not
needed either (it opens an extra Portal tab). Logging in by hand in the existing tab is enough.

Start reuses a verified Ops Chrome and starts one only when none exists. A brand-new profile
opens with exactly the two tabs; afterwards Chrome restores its own tabs, and Start opens a tab
only for a role that has none. It never closes a tab. SSO may open extra pages while you log in;
that is fine.

**Discarded tabs (measured 2026-10-01).** On this PC (about 0.4 GB of RAM free, on battery)
Chrome discarded the hidden Portal tab of the minimized Ops Chrome within minutes
(`document.wasDiscarded`). Playwright initialises every page when it attaches, so one discarded
tab made both workers' attach time out. The Dooray tab, which keeps a websocket, was never
discarded. Before every attach, each worker therefore checks every tab over a small loopback CDP
client. A tab that does not answer is restored with `Target.activateTarget`: Chrome reloads its
own URL with its existing session, the same as clicking the tab, and the window stays minimized.
Nothing is navigated, typed, evaluated or closed. A restored Dooray inbox settles for 15 s before
the unread guard starts. A tab that cannot be restored fails closed: Portal takes the existing
`PORTAL_CDP_ATTACH_TIMEOUT` path (one verified-browser recovery, then manual), and the Radar backs
off with `DOORAY_BROWSER_ABSENT`. Either worker may restore the other's discarded tab, because
that tab blocks both; neither ever navigates a live tab.

Which browser the workers attach to is `.local/ops-browser.json`: `{"mode": "unified"}` (the Ops
Chrome) or `{"mode": "separate"}` (the legacy Portal 9223 + Dooray 9222 browsers). A missing file
means `separate`; corrupt content fails closed. Sections 1-13 describe the workers themselves and
apply in both modes; where they name a port, the mode decides which one.

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
heartbeats use outbound HTTPS. Chrome CDP is **local loopback only**: the Ops Chrome on
9224, or in `separate` mode Portal 9223 and Dooray 9222. These are not public listening
services and must not be exposed through a firewall/router tunnel.

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
it starts only the dedicated browser of the current mode: the Ops Chrome
(`.local/ops-browser-profile` on 9224, Portal and Dooray tabs, session restore), or in
`separate` mode `.local/portal-browser-profile` on 9223 with the Portal landing page. A start
of the shared browser is serialised by `.local/ops-browser.lock`, so an operator Start and a
worker bootstrap never launch it twice. The worker then verifies ownership again
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

Status reports the browser mode, the poller lock, the Portal browser's
verified/missing/stale/unverified state (in unified mode also the Ops Chrome line and whether
its Portal and Dooray tabs are present), safe reason, and seconds since the last successfully
written healthy heartbeat.
It does not query any cloud service or display process/account/source identifiers,
environment variables, cookie material, notice titles or response bodies.
The Dooray Radar has its own lines:
* its enabled and running state;
* its last scan and last success;
* whether unread analysis is allowed;
* the port of the browser it uses (9224 unified, 9222 separate).

Status never starts a Dooray browser.

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

Unified mode (the normal case):

```cmd
scripts\windows\start_ops_browser.cmd
rem log in by hand in the Ops Chrome's Portal tab, then:
scripts\windows\start_ggongbab_workers.cmd
```

`separate` mode (after a rollback):

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
scripts\windows\recover_ops_browser.cmd
```

In unified mode this disables **both** workers and waits for their locks (Portal worker,
watchdog, Radar), then inspects only the Ops Chrome and makes one recovery attempt: a healthy
verified browser is reused, an absent one is started with its tabs, and only a verified
dedicated process that is stale (no listener) or behind a recorded `PORTAL_CDP_ATTACH_TIMEOUT`
is stopped and restarted. A missing Portal or Dooray tab is reopened. Then log in by hand where
a tab asks and start both workers again. `recover_portal_browser.cmd` does the same in unified
mode. In `separate` mode it keeps its original behaviour, described next.

`recover_portal_browser.cmd` in `separate` mode disables polling and waits for its lock,
inspects only the dedicated Portal Chrome, and makes one recovery/setup attempt. A known CDP attach timeout or a
matching non-listening stale process permits targeted restart. A healthy verified
browser is reused; an absent browser is started. Immediately before stopping a
stale process, Windows rechecks its exact command line, PID creation time and any
owner of that browser's port (9224 or 9223). An unrelated/reused PID or ambiguous owner aborts. No `taskkill /IM`,
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

Network/transport problems back off. A LIST connection that went stale during sleep or a
network change is not retried as is. After two consecutive transport failures, or on the first
failure after a wall-clock gap (resume from sleep), the worker closes its HTTP session. It then
takes a fresh one from the dedicated browser's existing login, after 30 s or a longer Retry-After
(`PORTAL_LIST_SESSION_REBUILT`). It does this at most three times per failure series. It never
deletes browser state or resets the baseline, and an expired login found while rebuilding stops
for SSO as usual. Beyond that, the worker permits five consecutive failed scans with exponential
delays (120, 240, 480, 900 seconds, and server Retry-After when longer). It then exits. The watchdog allows five additional starts after
the initial start, separated by 60/120/240/480/900 seconds or a longer Retry-After.
Budgets persist across watchdog/logon restarts. Ten minutes of continuously running
worker time with a recent successful scan replenishes the restart budget.
Exhaustion requires operator Start; there is no unlimited restart loop.

After a resume the watchdog gives the worker 10 minutes before it can latch
`OPS_WORKER_UNRESPONSIVE`. If that latch was set and scans later succeed again, it clears itself.

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
| PORTAL_LIST_SESSION_REBUILT | Informational: a stale LIST transport was replaced by a fresh session from the same login |
| DOORAY_AUTH_REQUIRED | Radar stops; complete SSO in the dedicated Dooray window, then `radar_tasks.ps1 -Action Start` |
| DOORAY_CONTRACT_CHANGED | Radar stops and unread analysis is disabled; re-run calibration, then `radar-allow-unread` and Start |
| DOORAY_UNREAD_INVARIANT_BROKEN | Unread rows are skipped until review; find what opened a mail or wrote during a scan, then `radar-allow-unread` |
| DOORAY_BROWSER_ABSENT | The browser or its Dooray tab is missing: `start_ops_browser.cmd` (unified) or open the dedicated Dooray browser on 9222 (separate); the Radar retries with backoff |
| DOORAY_BROWSER_UNVERIFIED | The listener is not positively the dedicated Chrome (profile, port, loopback, `chrome.exe`). The Radar never attaches; it retries with backoff and raises a critical alert. Run `status_ops_browser.cmd` and find what owns the port |
| OPS_BROWSER_UNVERIFIED / OPS_BROWSER_STALE | Start refuses an unknown/ambiguous owner or a dedicated process without a listener; use `recover_ops_browser.cmd` for the stale case only |
| OPS_WORKERS_STILL_RUNNING | The browser mode changes only while both workers are stopped |
| OPS_BROWSER_TAB_RESTORED | Informational: a tab Chrome had discarded/frozen was restored before an attach (section 0) |
| OPS_BROWSER_TAB_UNRESPONSIVE | A tab stayed dead after restore; Portal follows `PORTAL_CDP_ATTACH_TIMEOUT`, the Radar backs off. Click the tab, or `recover_ops_browser.cmd` |
| DOORAY_TRANSPORT_FAILED / DOORAY_WRITE_FAILED | Bounded backoff up to 15 min; nothing is marked processed until its task is written |

CDP timeout and owner failure keep their fixed reason in a `collector_error`
heartbeat, distinct from a confirmed auth-required failure. The process exit
remains compatible with the existing Portal command conventions.

## 12. Dooray Radar task

```powershell
powershell -NoProfile -File scripts\windows\install_dooray_radar_task.ps1 -PythonExe .venv\Scripts\python.exe
powershell -NoProfile -File scripts\windows\radar_tasks.ps1 -Action Start
powershell -NoProfile -File scripts\windows\radar_tasks.ps1 -Action Status
powershell -NoProfile -File scripts\windows\radar_tasks.ps1 -Action Stop
```

`Babdoduk-Dooray-Radar` uses the same model as the Portal task:
* Interactive logon, Limited privileges;
* no stored password;
* IgnoreNew;
* no WakeToRun;
* it starts 60 s after logon.

It runs `ggongbab_workers.py radar` against the Dooray tab of the Ops Chrome (in `separate` mode,
the dedicated Dooray browser), which the operator keeps open and minimized. Before every attach
it runs the same owner check as the Portal handoff (listener, loopback, `chrome.exe`, port, the
one expected user-data-dir); it uses only a top-level https page on the Dooray mail host, the
inbox preferred, and never the Portal tab. Start and Remove verify that the task belongs to this
checkout and this user before touching it. Stop persists `enabled=false` in `radar-control.json`; the Radar exits
within five seconds.

Before the first Start, use `ggongbab_workers.py radar-once --dry-run` to rehearse. It lists once
and registers nothing.

## 13. Operations checkout

The workers run from a dedicated clone, `C:\Users\joshu\Babdoduk-ops`. It is pinned to a
reviewed lab commit and has its own `.venv`, `.env` and `.local`. The development checkout can then
change branches without moving the collectors.

The migration is owner-gated:
1. Prepare the Python environment in the ops clone.
2. The owner creates its `.env`. Secrets are never copied by an agent.
3. Stop the old workers with Stop and verify that both locks are released.
4. Copy only the approved state. Each file is listed with its purpose and a SHA-256 in a manifest
   before the copy and checked after it. The approved files are:
   * `portal-list-state.json`: the Portal baseline, dedup ledger and pending ledger;
   * `ggongbab-mail-state.json`: the processed-mail ledger;
   * `dooray-ui.json` and `portal-ui.json`: the calibrated contracts.

   Not copied:
   * locks, logs, calibration diagnostics;
   * the ops runtime/budget/alert files, which the new workers regenerate (disabled until Start);
   * browser profiles.
5. Create fresh dedicated Portal and Dooray profiles in the ops clone. Cookies and profiles are
   never copied; the owner completes SSO in each.
6. Install both tasks from the ops clone and Start them.
7. Prove healthy scans and heartbeats and observe for 10–15 minutes.
8. Only then, remove the old checkout's task.

**Rollback.** Until step 8, the old checkout still holds its unchanged state, profiles and task.
Rollback is:
1. Stop the new tasks.
2. Start the old task.

Because state was copied, not moved, the old ledgers are exactly as they were at the stop. The old
worker can therefore re-detect items that the new workers handled in the meantime. For exact
continuity, copy the new ledgers back with the same manifest check before starting the old task.

## 14. Unified Ops Chrome: migration, proof and rollback

This is how two dedicated windows (Portal 9223, Dooray 9222) become one Ops Chrome (9224).
The migration never copies, extracts or decrypts cookies or other profile data between profiles,
and never touches the owner's own Chrome profile. The new profile starts empty and the owner
logs in by hand once in each tab.

1. Deploy the code with no `.local/ops-browser.json` (= `separate`): the workers keep the legacy
   browsers and behave as before.
2. `scripts\windows\start_ops_browser.cmd` creates `.local/ops-browser-profile` and opens the Ops
   Chrome on 9224 with the Portal and Dooray tabs, next to the untouched legacy browsers.
3. Owner checkpoint: Portal SSO in the Portal tab; Dooray SSO → 메일 → 받은메일함 in the Dooray tab.
4. Verify and prove, changing no worker state (no ledger, baseline, pending, heartbeat, task,
   mail state, flash, dispatch or unread latch; counts only, in `.local/ops-browser-proof.json`):

   ```cmd
   python scripts\windows\ggongbab_workers.py ops-browser-verify
   python scripts\windows\ggongbab_workers.py ops-browser-verify --cycles 10 --interval 60 --dooray-every 3
   ```

   Every cycle runs the Portal handoff with one LIST GET and, every third cycle, a dry-run Radar
   list scan under the unread guard. They run as two CDP clients that are attached at the same
   time. Each cycle checks the same Chrome PID and creation time, the same tabs on the same
   roles (no cross-navigation), no added page and no added window. PASS needs every scan to
   succeed, every Dooray cycle to overlap with Portal, exactly one window and zero unread-guard
   violations.
5. Cutover:

   ```cmd
   scripts\windows\stop_ggongbab_workers.cmd
   powershell -NoProfile -File scripts\windows\radar_tasks.ps1 -Action Stop
   python scripts\windows\ggongbab_workers.py ops-browser-mode --to unified
   scripts\windows\start_ggongbab_workers.cmd
   powershell -NoProfile -File scripts\windows\radar_tasks.ps1 -Action Start
   scripts\windows\status_ggongbab_workers.cmd
   ```

   `ops-browser-mode` refuses while any worker lock (Portal worker, watchdog, Radar) is held.
6. Close the two legacy browsers. Each one is closed only after it is verified (profile, port,
   loopback, `chrome.exe`), and the CDP endpoint must report that verified PID as its browser
   process before `Browser.close` is sent. A close that does not complete is reported, never
   forced. The profile directories stay as rollback assets.

   ```cmd
   python scripts\windows\ggongbab_workers.py legacy-browser-close --role portal
   python scripts\windows\ggongbab_workers.py legacy-browser-close --role dooray
   python scripts\windows\ggongbab_workers.py ops-browser-profiles
   ```

**Rollback** (state, ledgers, baselines and pending entries are never rebuilt; the Ops Chrome
profile is kept for diagnosis):

```cmd
scripts\windows\stop_ggongbab_workers.cmd
powershell -NoProfile -File scripts\windows\radar_tasks.ps1 -Action Stop
python scripts\windows\ggongbab_workers.py ops-browser-mode --to separate
python scripts\windows\ggongbab_workers.py legacy-browser-start --role dooray
scripts\windows\start_ggongbab_workers.cmd
powershell -NoProfile -File scripts\windows\radar_tasks.ps1 -Action Start
```

The Portal worker starts the legacy Portal browser itself when it is absent (section 4), or start
it explicitly with `legacy-browser-start --role portal`. If a legacy session has expired, log in
by hand in that browser. The Ops Chrome may stay open during a rollback: it uses its own port.

The opt-in real-browser test `tests/ggongbab/test_ops_browser_real_chrome.py`
(`BABDODUK_REAL_CHROME=1`) checks the shared layer on the installed Chrome with a throwaway
profile, port and local pages. It covers one window with two tabs, two overlapping CDP clients,
no closed, navigated or added tab or window, and a PID-bound close. It never contacts
Portal/Dooray.

## Dooray and cloud responsibility audit

`collectors/dooray.py` reads collection-project tasks, task bodies and optional
attachments via Dooray's project API. It cannot scan the authenticated web mail
inbox. Tasks may already be produced by Dooray's configured mail classification.
The local Dooray browser session (the Ops Chrome's Dooray tab; 9222 in `separate` mode) uniquely scans mail and creates candidate
project tasks; it is useful for missing classification coverage, recovery or
operator-requested backfill. Verified read-state rules still protect mail bodies.

The new installer **does not schedule Dooray** and does not add an ingest pipeline
to Portal. Audit any pre-existing `run_ggongbab_agent.cmd` task. If automatic mail
classification already covers the inbox, a second continuously scheduled local
mail bridge is unnecessary. If coverage is missing, decide which bridge owns that
mail population before scheduling it; do not blindly run both on the same mail.
Prefer one canonical pipeline writer (the cloud job), using local pipeline runs
only as deliberate operator recovery, not concurrent scheduled ingestion.

**Measured 2026-09-28 (MISS-001).** No Dooray mail classification was feeding the
project: the only mailbox scan ever recorded was the operator backfill of 2026-09-22,
and the cloud job saw the same 44 items from 2026-09-25 on. The local mailbox bridge
therefore owns the mail population. Its session and contract were recovered on
2026-09-28. A scheduled radar (list-level only, unread-safe) is Phase 2 of
`docs/GGONGBAB_DISCOVERY.md`. It triggers the cloud job with `--dispatch-refresh`
(`docs/GGONGBAB_TRIGGER.md`), never with `--run-pipeline`; the agent refuses the two together.

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

`.local/ops-alert.json` holds the Portal worker's own state:
* component;
* severity;
* action;
* fixed reason;
* success age;
* observed timestamp;
* worker-running flag.

`.local/ops-alerts.json` is the combined operator alert interface (Portal, Radar, dispatch, flash
candidates). The watchdog rewrites it every tick; see "Health targets and alerts" in
`GGONGBAB_DISCOVERY.md`. No third-party notifier is installed or message sent. A future external
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
