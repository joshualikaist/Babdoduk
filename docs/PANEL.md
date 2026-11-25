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
4. Commit those two paths with the run date and push through lab as usual.

## Page

`panel.html` (lab only: `vercel.json` answers 404 elsewhere; `noindex`; in the lab "more" menu as
가상 평가단). It shows the run, the panel's overall view, the top 10 with who raised each and the fix,
the members with their one-line summaries, and every thread as a chat (the critic on the right), filtered
by member and verdict (accepted by default). All text is inserted as text; a screenshot loads only from
`data/panel/shots/`. The page is left out of the visit counter (`js/site.js`). The conversation itself is
Korean; the page around it follows the language switch. Tests: `tests/test_panel.py`.
