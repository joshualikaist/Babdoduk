# 가상 평가단 (virtual review panel, lab only)

Owner request 2026-11-25: AI reviewers with different viewpoints review the lab site, and the owner reads
their conversation on one page. Designer and developer matter most (owner), so each reviews twice.

**It is a pre-screen, not user research.** Studies of AI "synthetic users" find them over-positive, prone to
invented issues and weak at prioritising (NN/g, Baymard, MeasuringU). The panel therefore requires evidence
for every finding, runs the important reviewers twice, and has a critic check each claim against the
screenshots, measurements or code. Confirm the top items with real students before large changes.

## Members (`.claude/agents/panel-*.md`)

| Member | Looks at | Standard |
| --- | --- | --- |
| 디자이너 ×2 | screenshots (iPhone 390, Android 412, computer 1440) | Nielsen's 10 heuristics, severity 0–4, `DESIGN_SYSTEM.md` |
| 개발자 ×2 | measurements in `facts.json` and the code | page-load targets (largest paint 2.5 s, layout shift 0.1), accessibility, maintainability |
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
   "capture": <run folder>}`: Review (six reviews) → Critic (merge and judge) → Reply (reviewers answer
   questions) → Verdict (final judgement and top 10). About eleven agents per run.
3. Save the workflow's return value as JSON and run
   `python scripts/panel/publish.py --result <file> --capture .local/panel/<run>`. It writes
   `data/panel/latest.json` and the cited screenshots as `data/panel/shots/*.webp` (480 px wide).
4. Run `python scripts/panel/live.py export --run <workflow run dir>` (the run's
   `.../subagents/workflows/wf_*` folder). It writes `data/panel/timeline.json`, the split-screen replay.
5. Commit those paths with the run date and push through lab as usual.

## Automatic runs (ops PC)

Owner request 2026-11-26: the panel runs by itself after lab changes, without anyone asking. The ops PC
does the five steps above unattended. These files live on that PC, not in the repository:

* `~/.config/babdoduk/panel-auto.sh`, started by the user timer `babdoduk-panel.timer` every hour from
  09:15 to 22:15 KST. It runs the panel only when `origin/lab` has a change outside `data/` since the last
  reviewed commit, the change is at least 30 minutes old (so it is deployed), and the panel has not run
  that day. So there is at most one run a day, and none when only generated data moved.
  `panel-auto.sh --now` runs it at once.
* A run makes a fresh worktree `../Babdoduk-wt/panel-MMDD` (branch `agent/claude/panel-MMDD`) from
  `origin/lab`, captures the lab site, runs `scripts/panel/workflow.js` with Claude Code in headless mode
  (`claude -p`, tools limited to Workflow, Write, Read, Glob and Grep), publishes `data/panel/`, commits
  it, runs `scripts/check_all.py --quick`, and sends the overall view and the top five to the owner's
  Telegram with the command `lab-push panel-MMDD`. It never pushes. The next run removes the worktrees the
  script made earlier. State and logs: `~/Babdoduk-ops/.local/panel-auto/`.
* `~/.local/bin/claude` starts the newest Claude Code program bundled with the VS Code extension, so there
  is nothing to install. `~/.local/bin/panel-login` (run once by the owner) signs in with
  `claude setup-token` and keeps the token in `~/.config/babdoduk/credentials/claude-oauth-token`
  (owner-only file). Without it the editor's sign-in is used, which expires every few weeks; when sign-in
  fails, Telegram says to run `panel-login`.
* `babdoduk-panel-live.service` keeps `scripts/panel/live.py watch` running from `~/Babdoduk-ops`, so
  http://127.0.0.1:8765/panel.html on that PC always shows the newest run live.

## Split screen, live and replay

Owner request 2026-11-26: see every reviewer at once, like a split terminal, while the review runs.
Each workflow agent writes its steps with timestamps to `agent-<id>.jsonl`, and `journal.jsonl` says which
agent is which reviewer. `scripts/panel/live.py` turns them into one timeline: one pane per reviewer
(디자이너 1·2, 개발자 1·2, 문구 담당, 창업가, 비판자), each step as a short Korean line (screen viewed,
file read, code searched, findings, comments). File paths become base names and commands are never shown.
The reviewers say one Korean sentence before each step (`.claude/agents/panel-*.md`), so the panes read
as narration.

* **Live, on this computer:** `python scripts/panel/live.py watch` serves the site on
  http://127.0.0.1:8765/panel.html and answers `data/panel/live.json` from the newest run (or `--run`)
  on every request; the page polls it every 2 s. It listens on 127.0.0.1 only. The lab site cannot be live:
  it is static, and publishing every step would mean a deployment every few seconds.
* **Replay, on lab:** the page plays `data/panel/timeline.json` at 1×, 10× (default) or 60×, with
  pause, restart and jump-to-end. With reduced motion it opens at the end.

## Page

`panel.html` (lab only: `vercel.json` answers 404 elsewhere; `noindex`; in the lab "more" menu as
가상 평가단). The split screen comes first (`js/panel-live.js`; it tries `live.json` only on 127.0.0.1 or
localhost). Below it the page shows the run, the panel's overall view, the top 10 with who raised each and the fix,
the members with their one-line summaries, and every thread as a chat (the critic on the right), filtered
by member and verdict (accepted by default). All text is inserted as text; a screenshot loads only from
`data/panel/shots/`. The page is left out of the visit counter (`js/site.js`). The conversation itself is
Korean; the page around it follows the language switch. Tests: `tests/test_panel.py`.
