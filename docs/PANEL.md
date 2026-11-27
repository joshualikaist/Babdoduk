# 가상 평가단 (virtual review panel, lab only)

Owner request 2026-11-25: AI reviewers with different viewpoints review the lab site, and the owner reads
their conversation on one page. Designer and developer matter most (owner). Since 2026-11-26 there is one of each (the owner cut the panel from two each to save usage).

**It is a pre-screen, not user research.** Studies of AI "synthetic users" find them over-positive, prone to
invented issues and weak at prioritising (NN/g, Baymard, MeasuringU). The panel therefore requires evidence
for every finding, has several viewpoints raise the same issue independently, and has a critic check each claim against the
screenshots, measurements or code. Confirm the top items with real students before large changes.

## Members (`.claude/agents/panel-*.md`)

| Member | Looks at | Standard |
| --- | --- | --- |
| 디자이너 | screenshots (iPhone 390, Android 412, computer 1440) | Nielsen's 10 heuristics, severity 0–4, `DESIGN_SYSTEM.md` |
| 개발자 | measurements in `facts.json` and the code | page-load targets (largest paint 2.5 s, layout shift 0.1), accessibility, maintainability |
| 문구 담당 | visible text and `i18n/ko.json` | Toss UX writing principles, the Copy section of `DESIGN_SYSTEM.md` |
| 창업가 | screens, `data/ggongbab/`, `PRD.md` | discovery → first value → return → referral; one question to ask a real student |
| 비판자 | every finding | merges duplicates, accepts, questions or rejects; ranks the top 10 |

Reviewers only read; none edits files, uses the network or touches protected systems.
Every agent runs on Sonnet (`MODEL` in `scripts/panel/workflow.js`, owner 2026-11-26): a run that inherited
the session's larger default model used about 50 million tokens before it was stopped.

## Run

1. `python scripts/panel/capture.py --out .local/panel/<run>`: opens the ten public pages on
   https://babdoduk-lab.vercel.app in Korean on the three devices (GET only) and writes `shots/*.jpg` and
   `facts.json` (headings, visible text, small tap targets, overflow, console errors, timings). Every
   reviewer reads this one capture.
2. Run `scripts/panel/workflow.js` with the Claude Code Workflow tool, `args` = `{"repo": <worktree>,
   "capture": <run folder>}`: Review (four reviews) → Critic (merge and judge) → Reply (reviewers answer
   questions) → Verdict (final judgement and top 10). About thirteen agents per run (four reviewers, critic, four discussants, up to four repliers, final verdict).
3. Save the workflow's return value as JSON and run
   `python scripts/panel/publish.py --result <file> --capture .local/panel/<run>`. It writes
   `data/panel/latest.json` and the cited screenshots as `data/panel/shots/*.webp` (480 px wide).
4. Run `python scripts/panel/live.py export --run <workflow run dir>` (the run's
   `.../subagents/workflows/wf_*` folder). It writes `data/panel/timeline.json`, the split-screen replay.
5. Commit those paths with the run date and push through lab as usual.

## On-demand runs (ops PC)

Owner correction 2026-11-26: start the panel with **평가 시작!** on the lab page and follow it there.
Opening the page only polls; it never starts a paid review. This replaces the earlier hourly schedule.
The ops PC does the five steps above after an authenticated request. The runner is `scripts/panel/auto.sh`;
`~/.config/babdoduk/panel-auto.sh` is its local launcher.

* `babdoduk-panel.timer` is disabled; the previous 19:55 retry timer is stopped. Usage-limit failures
  no longer schedule retries. The owner presses the button again after the displayed reset time.
  `babdoduk-panel.service` calls the local launcher with `--now`; the process lock and quota check always apply.
* A run makes a fresh **detached** worktree from `origin/lab`, preserving older worktrees and creating
  no task branch. It captures lab, runs the explicitly Sonnet-only workflow from the approved checkout,
  publishes `data/panel/`, commits only those paths, and runs the quick gates. It then pushes the results
  directly to lab (owner authorization 2026-11-26) and sends the existing Telegram summary with the lab
  page link. A source change on lab during the review stops publication; only content-bot data movement
  may be merged unattended. Pushes are ordinary, never forced, using the existing owner SSH alias
  `github-motar`. State and logs: `~/Babdoduk-ops/.local/panel-auto/`.
* The runner sets `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0`. Without it headless Claude Code stops background
  work 10 minutes after its last turn, and the first button run (22:47 KST on 2026-11-26) ended without a result
  after about ten minutes of reviewing.
* **Interrupted runs are not lost** (2026-11-26: two runs ended without a result, the second after 19 minutes at the
  usage limit, with all four reviews and the critic's merge already done). When the workflow returns nothing,
  `scripts/panel/salvage.py` rebuilds the result from the workflow's `journal.jsonl`: reviews and the critic's first
  judgement are kept, discussion, replies and the final verdict are left out, the top list is ranked by severity ×
  number of reviewers, and the overall text says the run stopped. That partial result is published like a full one,
  the Telegram message says it is partial, and a usage-limit wait is recorded again so the next press does not
  start into the same limit.
* `scripts/panel/auto_state.py` records a usage-limit failure and its reset time in private `status.json`.
  It waits five minutes after the provider's stated reset. Failed runs never write `ran-on`; only a
  successfully published result counts as today's completed run. A lock prevents overlapping runs.
  On 2026-11-26 the provider rejected the run at 15:24 KST with `usage_limit_reached`, resetting at
  19:50 KST. The old runner incorrectly marked that failed day as complete. The earliest allowed
  attempt is 19:55 KST, now requiring a new button press rather than an automatic retry.
* `~/.local/bin/claude` starts the newest Claude Code program bundled with the VS Code extension, so there
  is nothing to install. `~/.local/bin/panel-login` (run once by the owner) signs in with
  `claude setup-token` and keeps the token in `~/.config/babdoduk/credentials/claude-oauth-token`
  (owner-only file). Without it the editor's sign-in is used, which expires every few weeks; when sign-in
  fails, Telegram says to run `panel-login`.
* The optional local preview service is disabled. `babdoduk-panel-relay.service` publishes progress
  on lab without starting a paid review.

### Start request transport and authorization

The lab-only `/api/panel-control` accepts GET for status and a same-origin JSON POST for one fixed
`start` action. POST requires a Supabase access token, validated with Auth's `GET /auth/v1/user`, and
the server-owned `app_metadata.panel_operator === true` flag. User-editable metadata grants nothing.
The page reuses the existing account client, loading the SDK only after a signed-in person presses
the button; sign-in on `my.html?next=panel` returns to the lab panel. No backend key is deployed.

`scripts/panel/control.py` uses the existing ops backend key. It provisions **private** Storage bucket
`panel-requests` (JSON only, 16 KB), accepting only `pending.json`. It publishes a five-second heartbeat
and a two-hour, single-object, overwrite-only signed upload capability in `panel-live/control.json`.
The lab API projects status only on GET; on authorized POST it uses the capability to upload a private
request containing a UUID, timestamp and short-lived user access token. A capability alone grants no
read or review execution. The worker independently revalidates the token and operator flag, rejects
stale/extra-field/replayed requests, removes the private inbox object, then starts only the fixed
systemd unit. Accepted UUIDs are persisted before launch, and a running unit or active quota blocks
another start. A missing acknowledgment after 30 seconds lets the owner retry without claiming success.

The public write capability is deliberately bounded to one small private object. Someone who bypasses
the API can replace that inbox and delay a valid request; they cannot read its token or start a review
without a valid operator session. A future managed queue with authenticated writes could remove this
availability limitation. This transport adds no SQL/RLS changes or Vercel secret configuration.

Install `scripts/panel/control.service` as `babdoduk-panel-control.service`, substituting the approved
worktree. Provision once with `control.py --env-file ~/Babdoduk-ops/.env --setup`. After the owner confirms
the exact existing sign-in email, grant only that account with `--grant-email <email>`; the command
preserves other application metadata. No roles are inferred from Git author identity or client fields.
The CLI requires an existing account; it never creates an account or signs in as the owner.

Protocol references: [signed upload URLs](https://supabase.com/docs/reference/javascript/storage-from-createsigneduploadurl),
[uploading to a signed URL](https://supabase.com/docs/reference/javascript/storage-from-uploadtosignedurl),
[server-owned application metadata](https://supabase.com/docs/guides/auth/managing-user-data).

## Split screen, live and replay

Owner request 2026-11-26: see every reviewer at once, like a split terminal, while the review runs.
Each workflow agent writes its steps with timestamps to `agent-<id>.jsonl`, and `journal.jsonl` says which
agent is which reviewer. `scripts/panel/live.py` turns them into one timeline: one pane per reviewer
(디자이너 1·2, 개발자 1·2, 문구 담당, 창업가, 비판자), each step as a short Korean line (screen viewed,
file read, code searched, findings, comments). File paths become base names and commands are never shown.
The reviewers say one Korean sentence before each step (`.claude/agents/panel-*.md`), so the panes read
as narration.

* **Live, on lab:** the lab page polls `/api/panel-live` every
  5 seconds. `scripts/panel/relay.py` follows only panel workflows and sends a sanitized timeline to a
  dedicated public Storage object whenever the source or safe status changes. This needs no Git commit, deployment or browser
  connection to the ops PC per step. The API accepts GET only on the lab host and uses the existing
  publishable configuration server-side; the page loads no Supabase client or backend configuration.
  The snapshot time is the source file's last modification, not a fabricated heartbeat. After 90 seconds
  without source activity, or on a failed request, the page shows an interrupted connection and keeps
  the last received steps, except while a review is requested or running (`panel-control.js` announces it
  with the `babdoduk-panel-busy` event): the screens are captured for about two minutes before the relay has
  anything new, so the page then says "preparing", dims the previous run and does not claim a lost connection
  (owner 2026-11-26). A completed final critic result switches to a finished replay. An open replay
  keeps checking for the next run. Parallel reviewers' late and retried events are reconciled.
* **Optional local preview:** `python scripts/panel/live.py watch` serves the site on
  http://127.0.0.1:8765/panel.html and answers `data/panel/live.json` from the newest run (or `--run`)
  on every request; the page polls it every 5 s. It listens on 127.0.0.1 only.
* **Replay, on lab:** until live data is available, the page plays `data/panel/timeline.json` at
  1×, 10× (default) or 60×, with
  pause, restart and jump-to-end. With reduced motion it opens at the end.

### Backend and runtime activation

Owner authorization 2026-11-26: all panel activation and repair steps approved. The implementation uses
one dedicated Supabase Storage bucket, `panel-live`, with only `current.json` (JSON only, 2 MB maximum).
It is public **read**, so its sanitized contents are directly addressable; the lab host restriction is
not authentication. Only the operations computer's existing backend key uploads. No browser Storage
write policy is added. The proposed custom table/RPC migration was not applied; no schema migration is
needed for this transport. The API reads the public object server-side and projects its fields again.

Provision with `python scripts/panel/relay.py --env-file ~/Babdoduk-ops/.env --setup`. This creates only
that bucket if absent, validates its exact configuration if it exists, and never changes another
bucket or a mismatched pre-existing configuration. Uploads replace the single object with cache age 0;
the lab API requests an uncached version every five seconds. A relay process lock prevents concurrent
local publishers. The script never starts models or sends messages.

Install `scripts/panel/relay.service` as `babdoduk-panel-relay.service`, substituting the approved source
checkout for the placeholder. Keep that checkout while the service uses it. The private ops `.env`
stays where it is. The local preview service is optional; visitors open
https://babdoduk-lab.vercel.app/panel.html. The automatic-review launcher also points to this approved
checkout, so the Sonnet pin and retry handling do not depend on a stale ops checkout.

Source logs remain local. Only allowlisted timeline fields and a fixed usage-limit code/retry time are
published. Absolute paths, URLs, emails and credential-like narration are redacted. This bucket/public
object is the owner's approved exposure (see `docs/PUBLIC_EXPOSURE.md`). The relay route rejects
production and preview hosts. Backend errors are never returned to the browser.

Verify the deployed API and KO/EN panel page. Synthetic tests cover interrupted, completed, quota and
retry states without invoking a paid reviewer. Live checks must verify anonymous writes are denied,
the actual source snapshot reaches lab, and the provider accepts a later scheduled review; passing
synthetic checks alone does not prove those external services are healthy.

## Page

`panel.html` (lab only: `vercel.json` answers 404 elsewhere; `noindex`; in the lab "more" menu as
가상 평가단). The split screen comes first (`js/panel-live.js`; it reads `/api/panel-live` on lab and
`live.json` only on 127.0.0.1 or localhost). Below it the page shows the run, the panel's overall view, the top 10 with who raised each and the fix,
the members with their one-line summaries, and every thread as a chat (the critic on the right), filtered
by member and verdict (accepted by default). All text is inserted as text; a screenshot loads only from
`data/panel/shots/`. The page is left out of the visit counter (`js/site.js`). The conversation itself is
Korean; the page around it follows the language switch. Tests: `tests/test_panel.py`, `tests/test_panel_relay.py`,
`tests/test_panel_control.py`. Synthetic tests never invoke the live runner or provider.
