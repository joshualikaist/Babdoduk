# Babdoduk agent working rules

This is the repository operating manual for human and AI changes. The current product direction is in `PRD.md`, UI contracts in `DESIGN_SYSTEM.md`, and implementation boundaries in `ARCHITECTURE.md`. Follow a direct user instruction when it explicitly changes the task scope; otherwise treat unresolved owner decisions as unresolved.

This copy describes the `main` (production) baseline. Systems marked **Lab-only / not promoted to production in the current main baseline** exist only on the `lab` branch; their documents live there, not here.

The rules here are authoritative. The step-by-step procedures that carry them out live in `.claude/skills/<name>/SKILL.md`: `session-start`, `handoff`, `verify-babdoduk`, `release-babdoduk` and `ui-review`. They are plain Markdown, so any agent can follow them.

## Before starting

1. Read the documents the task needs: `PRD.md` for product scope, `DESIGN_SYSTEM.md` for visual work, `ARCHITECTURE.md` for system boundaries, `README.md` and the `docs/` file governing the feature. Inspect the implementation and tests before planning a replacement.
2. Follow the session-start procedure. Preserve unrelated or user-owned changes. Do not assume a local `main` or cached remote ref describes the deployed site.
3. State the intended file scope. Separate frontend presentation from generated data, canonical DB, local agents and deployment operations.
4. Work on your own task branch in your own worktree. Never change `main`, merge to it, deploy production or force push without explicit owner authorization. Do not reset or rebase over pushed or generated-data commits.

## Git / Multi-Agent Session Protocol

### Branches

- `main` is production. A push or merge to `main` deploys https://babdoduk.vercel.app through Vercel's Git integration. Agents never modify `main` without explicit owner authorization, and a full `lab` → `main` merge is never the default.
- `lab` is the integration/staging branch (https://babdoduk-lab.vercel.app). It is not a general scratch branch; agents do not normally develop directly on it. Integrating a task branch into `lab` is a separate, authorized step.
- Task branches are `agent/claude/<task>`, `agent/codex/<task>`, `agent/cursor/<task>` (or `agent/<tool>/<task>`). Each starts from the latest `origin/lab` unless the task explicitly targets production or a hotfix.
- Release branches are `release/<name>`, started from a recorded `origin/main` SHA. They carry only owner-approved changes into a production candidate (for example by `git cherry-pick -x`), are reviewed through a pull request and Preview deployment, and are merged only with explicit owner approval. The canonical procedure is `release-babdoduk`.

### Worktrees

- ONE WORKTREE = ONE ACTIVE CODING AGENT. Claude, Codex, Cursor and the owner must not edit the same working tree at the same time: it shares one filesystem and one Git index, so one agent can stage, commit or test another's changes.
- Prefer one separate worktree per active agent/task under `../Babdoduk-wt/` (commands in `session-start`).
- Do not link an agent or release worktree to a Vercel project and never run `vercel --prod`. Never deploy with the Vercel CLI from a working tree that has uncommitted changes.
- If another agent appears to be using the tree (unexpected edits, lock files, an operation in progress), stop and report before editing. Never delete or remove an unknown worktree, lock file or stash.

### Changes, commits and pushes

- Anything that existed before your session (modified or untracked files, stashes, branches, worktrees) is not yours: never stage, restore, stash, commit or delete it.
- Record the starting state before editing (`session-start`), and report the ending state, remote movement and exact test results when you finish (`handoff`).
- Stage explicit session-owned paths only (`git add -- <path...>`). Never use `git add -A`, `git add .` or `git commit -a` when unrelated changes exist.
- Commit coherent, completed work with an `Agent: <tool>` trailer (`Agent: Claude`, `Agent: Codex`, `Agent: Cursor`). All tools share the `joshualikaist` Git identity, so the trailer is the only attribution; do not infer authorship of historical commits from style. Do not present incomplete work as finished; a WIP commit needs owner permission and a `WIP:` subject.
- Push only your own task branch, only when the task authorizes it, and never with force. A task branch is not permission to push to `lab` or `main`.

### Forbidden without the owner authorizing the exact operation

`git push --force`, `git push --force-with-lease`, `git reset --hard`, `git clean -fd`, `git checkout -- .`, `git restore .`, automatic resolution of a diverged branch, deleting unknown stashes and deleting unknown worktrees. A non-fast-forward push rejection is a safety signal: fetch, report the new commits and integrate deliberately through the task branch or release process. Never bypass it. In Claude Code, `.claude/hooks/git_guard.py` also blocks the destructive forms of these commands and `vercel --prod`.

### Generated-data bot

GitHub Actions (`babdoduk-content-bot`, via `scripts/publish_generated.py`) pushes generated `data/magazine/`, `data/kaist-menu/` and `data/ggongbab/` files to both `origin/lab` and `origin/main` without any interactive agent, several times a day, and each push also triggers a Vercel deployment. Such commits are expected movement: identify them by the bot identity and data-only paths, and do not treat them automatically as another agent's conflicting work. Never force-push over them.

## Implementation discipline

- Reuse existing patterns before adding a new one. The static HTML/CSS/JS architecture needs a demonstrated problem before a build system or framework migration is proposed.
- Shared navigation and footer styles belong to `css/site.css` only; page translations and some component styles are still duplicated per page. Inspect every consumer and edit scoped locations; never run a blind global rewrite. `rebuild_index.py` and `patch_site.py` contain historical templates and must not be run without comparing their output against current pages.
- Do not manually edit generated `data/magazine/`, `data/kaist-menu/`, `data/ggongbab/latest.json` or `data/foods/` to make UI tests pass. Preserve their schemas, validators, provenance and branch publication rules. `data/food-log.json` and `data/ggongbab/manual.json` are authored inputs, not generated output.
- Keep fixture and localhost preview behavior separate from normal routes. `lab-ggongbab.html` is `noindex` but that is not access control. Never let preview, raw mail, credentials or private DB content enter public HTML or JSON.
- Preserve keyboard access, visible focus, status announcements, Korean/English copy, long-text wrapping, reduced-motion behavior and the existing scrollbar design. A visual task must not relax an assertion, publication rule or security gate.
- Keep localStorage keys and existing user data readable. Do not silently replace user-selected filters or food records.
- Distinguish verified facts, inferred states, authored material, generated fallback and suggestions in copy and metadata.
- Do not log or commit passwords, API tokens, JSESSIONID, browser profiles, unredacted mail, raw Portal IDs or private source URLs.

## Protected boundaries and explicit authorization

Ask for a task specifically targeting these before changing them: `supabase/migrations/`, RLS, grants, Realtime publication or RPC; `scripts/ggongbab/` collectors, parsers, dedup, sanitizer, validator and exporter, and the public JSON contract; Dooray and Portal agent/session behavior; Windows scheduled workers; GitHub Actions workflows and schedules (including repairing `.github/workflows/ggongbab-refresh.yml`); secret/configuration deployment; generated JSON schema; live authentication or live collector runs; `main` and production deployment. A presentation task does not authorize any of these.

Portal notice detail GET (`/wz/api/board/recents/{post_id}`) stays blocked, as do authentication replay and credential or OTP/MFA automation. Manual KAIST SSO/MFA remains human work. The cloud Portal collector on `main` is disabled. Lab-only / not promoted to production in the current main baseline: a Portal LIST-only session poller that may call only the pinned recent-post LIST GET, whose titles are only a Stage A signal (documented on the `lab` branch in `docs/PORTAL_LIST_POLLER.md`).

Dooray body/detail use requires a verified read-state field and explicitly already-read rows. Missing or unknown state fails closed before body access. See `scripts/ggongbab/web/calibrate.py`, `docs/GGONGBAB_PREVIEW.md` and their synthetic tests.

On `main`, public pages read only the validated static snapshot `data/ggongbab/latest.json` (plus the other generated JSON files); private canonical tables and backend credentials stay outside the frontend, and the browser holds no Supabase configuration. Lab-only / not promoted to production in the current main baseline: an allowlisted public DB projection read by the browser through Supabase SELECT/Realtime with a static fallback (documented on the `lab` branch in `docs/GGONGBAB_PUBLIC_FEED.md` and `docs/GGONGBAB_REALTIME.md`). Promoting it needs its own authorized task covering migrations, backend publication and frontend together.

## Verification by change type

Run focused tests first, then the relevant full gate before completion. Do not use a live Dooray/Portal account or Supabase project as a synthetic test fixture.

| Change | Required checks |
| --- | --- |
| Documentation only | Check links and facts against current code/docs on the same branch; review diff and status |
| General frontend | `python -m pytest tests -q`, `python scripts/validate_content.py`, `python scripts/check_site_ui.py`; inspect mobile/tablet/desktop and keyboard behavior |
| Ggongbab or menu frontend | General frontend checks plus `python scripts/check_ggongbab_ui.py`; preserve the fixture clock only in fixture mode and fixed-clock scenarios, the initial all-upcoming filter, saved filters, public eligibility, Radar and featured |
| Pipeline or contract, explicitly authorized | Contract-specific synthetic tests plus full suite and content validator; review private/public field boundaries and failure exits |
| Generated-data workflow, explicitly authorized | Validate only selected generated paths and publication branch behavior; never merge feature code through `publish_generated.py` |

Checks must not depend on the wall clock: a scenario that needs "today" fixes the page clock and derives its synthetic data from the same reference time. Report every gate's first result, including failures, and never weaken an assertion to pass (procedure: `verify-babdoduk`). Tests are evidence for the code under test, not proof that external services, production deployment or data freshness are healthy. State what was not tested.

## Handoff

Report changed files, the user-visible result, tests and counts, remaining risks, remote movement, and the branch with its exact commit and push state (procedure: `handoff`). If the task is interrupted, leave a concise continuation prompt with current SHA, worktree changes, completed phase, next phase, open owner decisions and commands needed to resume. Never leave a half-finished unreviewed mutation disguised as complete.
