# Handoff: continuing Babdoduk on another PC (2026-10-17)

State of the project and of the owner's PC at the end of the 2026-10-16/17 session, and what a second
machine needs. It contains no secrets. It sits on a task branch (`agent/claude/new-pc-handoff`) and is
not merged into `lab` or `main`.

**Plan as of 2026-10-17 (owner):** the new machine is a Linux desktop with a display. It becomes the
only development machine, the ops workers are ported to Linux (section 7), and once the Linux workers
are proven the Windows PC is wiped (section 8). Until that cutover the Windows PC keeps running the
workers. Section 3 describes the Windows install and applies to Linux only after the port.

## 1. What is already in git (nothing to copy)

All code, tests, docs and data are on `origin`. At the end of this session:

| Branch | Meaning | Head (before later bot commits) |
| --- | --- | --- |
| `origin/main` | production, https://babdoduk.vercel.app | `9290052` |
| `origin/lab` | staging, https://babdoduk-lab.vercel.app | `c3609cb` |

Released to production on 2026-10-16 (`efb4f42`, release branch `release/kakao-e2e-polish-20261016`):
KakaoTalk share card on the world cup result, E2E stage 2 (`scripts/e2e_browsers.py`) and stage 4
(`scripts/e2e_quality.py`), prompt v5 plus header-only sanitizer, and the UI polish (44 px tap targets,
darker text on the magazine and picker, reserved space against layout shift, WebP thumbnails, weekend
cafeteria wording). Lab was back-synced (`e34dd36`); the drift check
`git log --format='%h %an %s' origin/lab..origin/main | grep -v babdoduk-content-bot` prints nothing.

Deliberately NOT on `main` (owner decision 2026-10-16):
- the `.github/workflows/e2e-live.yml` changes (manual `browsers` and `quality` targets);
- the E2E stage 3 harness (`scripts/e2e_ggongbab_flow.py`, its fixtures and test), because it imports
  the lab-only Dooray Radar. It lives on `lab`.

## 2. What is NOT in git, and must never be committed

On the current PC, all of this is in `C:\Users\joshu\Babdoduk-ops` and is ignored (`.local/`, `.env`):

- `.env` (Supabase and other secrets): the owner creates it by hand on the new PC.
- `.local/` runtime state: browser profiles (`ops-browser-profile`, `dooray-browser-profile`), cookies and
  logins, locks, logs, alert state, `ops-python.txt`.
- The Dooray and KAIST Portal SSO/MFA logins: done by hand in the browser on each machine.
- Claude Code's own memory (`~/.claude/projects/<project>/memory/`): per machine, not in git. Section 5
  restates what matters.

## 3. Setting up the operations checkout on the new PC

The procedure is `docs/GGONGBAB_RESIDENT_OPS.md` (section 3 "Install", section 13 "Operations checkout").
In short:

1. Clone the repository to a dedicated folder and check out `lab` at a reviewed commit:
   `git clone https://github.com/joshualikaist/Babdoduk.git C:\Users\<you>\Babdoduk-ops`, then
   `git checkout lab`.
2. Create a `.venv` and install `requirements-ggongbab.txt`; Google Chrome must be installed.
3. Create `.env` from `.env.example` by hand.
4. Install the tasks from this checkout: `scripts\windows\install_ggongbab_tasks.ps1` and
   `scripts\windows\install_dooray_radar_task.ps1` (pass `-PythonExe .venv\Scripts\python.exe`).
5. Open the Ops Chrome with `scripts\windows\start_ops_browser.cmd`, log in by hand to the Portal tab and
   to the Dooray tab (then 메일 → 받은메일함), then start the workers
   (`start_ggongbab_workers.cmd`, `radar_tasks.ps1 -Action Start`).
6. Check `scripts\windows\status_ggongbab_workers.cmd` and watch scans and heartbeats for 10-15 minutes.

Things to know before you do this:

- **Run the workers on one PC at a time.** The locks (`.local/*.lock`) are per machine, so two PCs would
  both scan the same mailbox and Portal. This session did not check how well the cloud side de-duplicates
  that. Stop and remove the tasks on the old PC (`stop_ggongbab_workers.cmd`,
  `radar_tasks.ps1 -Action Stop`, then Remove) before starting on the new one.
- **State to carry over is optional.** The dedup and processed-mail ledgers
  (`portal-list-state.json`, `ggongbab-mail-state.json`) and the calibrated contracts (`dooray-ui.json`,
  `portal-ui.json`) can be copied by hand with a SHA-256 manifest, as section 13 describes. Without them
  the new PC starts from a fresh baseline; `radar-recheck --days 7` can re-read recent mail.
- **The old ops checkout is behind.** At the end of this session `C:\Users\joshu\Babdoduk-ops` was at
  `24a75ef`, 156 commits behind `origin/lab`, so it does not yet run prompt v5 or the header-only
  sanitizer. A new clone of `lab` gets them.
- The cloud dispatch is off (`radar-dispatch-on` is not set), and the cloud cron runs `main`'s code.

## 4. Working on the code from the new PC

Follow `AGENTS.md` and `CLAUDE.md`: start a task branch from the latest `origin/lab` in its own worktree
(`/session-start`), reach production only through lab (`/release-babdoduk`, owner-run), and never push
`main` or force-push. Worktrees go in an absolute path next to the checkout, never inside another clone.

Handy facts from this machine's Windows shell setup (they may differ on the new PC):
- Git Bash rewrites `rev:path` arguments: prefix with `MSYS_NO_PATHCONV=1`.
- Printing Korean needs `PYTHONIOENCODING=utf-8` (console is cp949).
- Write files that contain backslash escapes with the editor tools, not with a shell heredoc.
- Tests ran with the ops venv: `...\Babdoduk-ops\.venv\Scripts\python.exe -m pytest tests -q`.

## 5. Open items

- Run the world cup on production on a phone: sound, story share, KakaoTalk share (not tested on a device).
- Remove the lab-only `previewFrom` from `js/worldcup-gate.js` on lab (the world cup is
  open 2026-10-16 to 2026-10-23 KST by the client clock).
- `#mgHeroMediaLink` (the magazine hero's photo link) has no accessible name while its external photo is
  still loading, so axe reports an intermittent `link-name` serious on mukbang and choose. It predates
  this release. Fix: give the link the story title as `aria-label`, through lab.
- The hub in English on a phone still shifts a little (CLS about 0.12-0.16): the web font swap rewraps
  the filter chips.
- Holidays show the weekday cafeteria wording; the site cannot know holidays.
- The owner deletes the remote `release/*` branches once production has been stable for 1-2 weeks, and
  the unpushed local branch `release/e2e-kakao-polish-20261016` (an abandoned first attempt;
  `git_guard.py` blocks agents from deleting branches).
- Vercel's free tier rate-limited both projects on 2026-10-14: avoid needless pushes.
- Dooray body/detail use still needs a verified read-state field; the Portal notice detail GET stays
  blocked; manual KAIST SSO/MFA stays human work.

## 6. Owner preferences that carried the sessions

- Reply to the owner in Korean; ask before each real error or decision.
- Delegate mechanical work (gates, previews, repetitive edits, merges) to Sonnet subagents; keep the
  stronger model for design, review and debugging.
- Baselines (`docs/VISUAL_BASELINES.md`) change only with the owner's explicit approval.
- Lab first, then `main`; local tests passing is not lab approval.

## 7. Porting the ops workers to Linux (owner-authorized 2026-10-17)

The owner chose to port the Dooray Radar and the Portal LIST worker to the Linux desktop and then retire
the Windows PC. This authorizes a task that targets the Windows scheduled workers and their launch,
process and notification layer. It does not change what the collectors may read: Portal LIST-only, no
Portal notice detail GET, Dooray body access only behind the verified read-state guard, no
authentication replay, manual SSO/MFA, loopback-only CDP. Those rules and their tests stay as they are.

Do it on the Linux machine, where a real Chrome and the SSO logins can be tested, on a task branch from
the latest `origin/lab` (the workers run `lab`, so the port does not need `main`).

What is Windows-only today (`git grep` on `origin/lab`, 2026-10-17):

| File | Windows-only part | Likely Linux equivalent |
| --- | --- | --- |
| `scripts/windows/ggongbab_workers.py` | refuses to run unless `os.name == "nt"` | allow `posix`, keep the `lab` branch check |
| `scripts/windows/*.ps1`, `*.cmd` | Task Scheduler install/start/stop/remove, launchers | `systemd --user` units (Restart=on-failure, after the graphical session) and small shell scripts |
| `scripts/ggongbab/windows_portal_host.py` | process ownership via PowerShell `Win32_Process`, `ctypes.windll` argv split | `/proc/<pid>/cmdline` (or `psutil`) |
| `scripts/ggongbab/resident_ops.py` | `CREATE_NO_WINDOW` launches, Windows toast | plain `subprocess`, `notify-send` |
| `scripts/ggongbab/notify.py` | Windows toast and its PowerShell/`windll` helper (around line 172) | `notify-send`; Telegram/ntfy push is already portable |
| `scripts/ggongbab/portal_session.py`, `web/resident.py`, `dispatch.py` | `os.name != "nt"` guards, a PowerShell process query | the same `/proc` inventory |
| `scripts/ggongbab/portal_list_state.py` | already has `msvcrt` and `fcntl` branches | check that the `fcntl` path is tested |
| Ops Chrome start | `chrome.exe` path, `STARTUPINFO` minimized start | `google-chrome` with the same `--user-data-dir` and `--remote-debugging-address=127.0.0.1 --remote-debugging-port=9224` |
| `scripts/check_site_ui.py` | baseline set chosen by OS and `BABDODUK_BROWSER` | run the gate in the pinned CI image (`docs/VISUAL_BASELINES.md`) or get an owner-approved Linux set |

Cutover, in this order:
1. On Linux: clone, `git checkout lab`, `.venv`, `pip install -r requirements-ggongbab.txt`, the `.env`
   from the transfer zip. Run the full synthetic suite.
2. Implement the port. Rehearse with `ggongbab_workers.py radar-once --dry-run` (it lists once and
   registers nothing) while the Windows workers still run. Do not Start the Linux workers yet.
3. On Windows: stop the workers (`scripts\windows\stop_ggongbab_workers.cmd`,
   `powershell -NoProfile -File scripts\windows\radar_tasks.ps1 -Action Stop`) and check that both locks
   are released.
4. Copy the current state files from `C:\Users\joshu\Babdoduk-ops\.local\` (`ggongbab-mail-state.json`,
   `portal-list-state.json`, `dooray-ui.json`, `portal-ui.json`). Copy them again at this moment: the
   copies in the 2026-10-17 transfer zip are already stale.
5. On Linux: open the Ops Chrome, log in by hand (Portal; Dooray, then 메일 → 받은메일함), start the
   workers, and watch scans, heartbeats and alerts for 10-15 minutes.
6. Only then retire the Windows PC (section 8). Until step 6 the rollback is to start the Windows workers
   again.

## 8. Retiring the Windows PC (only after section 7 step 5 is healthy)

1. Remove the tasks from `C:\Users\joshu\Babdoduk-ops`:
   `powershell -NoProfile -File scripts\windows\remove_ggongbab_tasks.ps1` and
   `powershell -NoProfile -File scripts\windows\radar_tasks.ps1 -Action Remove`. Check in Task Scheduler
   that `Babdoduk-Portal-Worker` and `Babdoduk-Dooray-Radar` are gone.
2. Close the Ops Chrome window.
3. Delete the folders:
   - `C:\Users\joshu\Babdoduk-ops` (1.5 GB: `.env`, logins, browser profiles, `.venv`);
   - `C:\Users\joshu\Babdoduk` (929 MB: the old clone, with the current checkout `Babdoduk\Babdoduk`
     inside it);
   - `C:\Users\joshu\Babdoduk-wt` (the old clone's worktrees and logs);
   - `C:\Users\joshu\Babdoduk-transfer` (transfer zip and backup bundles), after they are on Linux.
4. Delete the three desktop shortcuts (`밥도둑 Ops Chrome 열기`, `밥도둑 Ops Chrome 복구`,
   `밥도둑 상태 확인`) and `Downloads\Babdoduk_Claude_Development_Handoff_2026-10-12.md`.
5. Delete Claude Code's project data: `C:\Users\joshu\.claude\projects\c--Users-joshu-Babdoduk*`
   (three folders).
6. Optional: remove the GitHub entries from Windows Credential Manager if this PC no longer uses
   GitHub, and rotate the keys in `.env` (Supabase secret, OpenAI, Dooray token) because the file has
   been copied between machines.

Nothing else on this PC belongs to Babdoduk: no user environment variables, no startup entries and no
other scheduled tasks matched on 2026-10-17.

Backup made before the wipe (2026-10-17), in `C:\Users\joshu\Babdoduk-transfer\backup\`:
`old-clone-Babdoduk.bundle` (every ref of the old clone, its stash included) and
`ops-clone-Babdoduk-ops.bundle` (every ref of the ops clone), both `git bundle verify`-ed, plus `notes\`
(untracked notes and the old clone's uncommitted diff). Every local branch of the old clone was already
contained in `origin/lab`; the ops clone held two superseded drafts. Restore with
`git clone old-clone-Babdoduk.bundle` or `git fetch <bundle> 'refs/*:refs/backup/*'`.
