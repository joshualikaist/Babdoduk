# Babdoduk agent working rules

This is the repository operating manual for human and AI changes. The current product direction is in `PRD.md`, UI contracts in `DESIGN_SYSTEM.md`, and implementation boundaries in `ARCHITECTURE.md`. Follow a direct user instruction when it explicitly changes the task scope; otherwise treat unresolved owner decisions as unresolved.

Systems marked **Lab-only / not promoted to production in the current main baseline** exist only on the `lab` branch, together with their documents; `main` never carries them.

The rules here are authoritative. The step-by-step procedures that carry them out live in `.claude/skills/<name>/SKILL.md`: `session-start`, `handoff`, `verify-babdoduk`, `release-babdoduk` and `ui-review`. They are plain Markdown, so any agent can follow them.

## Lab-first lifecycle (non-negotiable)

Product, UI, frontend, copy, navigation, page-design and responsive changes, and documentation tied to product behavior, always reach production through `lab`:

1. **Task:** start a task branch from the latest `origin/lab`, in your own worktree.
2. **Lab integration:** integrate the task branch into `lab` (an authorized step of its own).
3. **Lab deployment:** wait for the `Vercel – babdoduk-lab` deployment of that exact `lab` commit to succeed.
4. **Lab verification:** check the change visually and functionally on https://babdoduk-lab.vercel.app, in Korean and English.
5. **Owner approval** of what is deployed on lab.
6. **Release candidate:** from the latest `origin/main`, promote only the exact approved task commits. Never merge `lab` as a whole into `main`: lab also carries experiments that are not production-ready.
7. **Production:** run the gates again on the exact candidate, push `main` normally (never force), and verify production.
8. **Back-sync:** bring the released production commits back into `lab`, so staging is again the production baseline plus intentional lab-only experiments.

Product/UI/frontend tasks always start from the latest `origin/lab`. **A production destination does not by itself authorize a main-based task.** "Update the site", "refresh production", "prepare a release" and "fix the page and deploy it" are ordinary releases: they go through lab. Local tests passing is not lab approval.

Starting from `main` (bypassing lab) is allowed only for:
- an emergency production hotfix that the owner explicitly authorizes to bypass lab;
- generated-data bot publication (`babdoduk-content-bot`, see below);
- production infrastructure recovery that the owner explicitly authorizes, where lab cannot represent the target (for example a workflow that only runs from `main`);
- a repository-only emergency fix that the owner explicitly says must bypass lab.

Record the owner's bypass authorization in the task report. A bypass change is back-synced into `lab` in the same task.

**Lab never trails production.** If `origin/main` has a source commit that `origin/lab` lacks (generated-data bot commits aside), staging no longer previews production: back-sync it before starting product work. A release is not operationally complete until that back-sync is pushed and deployed to babdoduk-lab. The procedures are `session-start` (the drift check), `release-babdoduk` (the lab acceptance gate, selective promotion and back-sync) and `handoff`.

## Before starting

1. Read the documents the task needs: `PRD.md` for product scope, `DESIGN_SYSTEM.md` for visual work, `ARCHITECTURE.md` for system boundaries, `docs/GUIDE.md` (pages, data, pipelines and operations; `README.md` is only the short overview) and the `docs/` file governing the feature. Inspect the implementation and tests before planning a replacement.
2. Follow the session-start procedure. Preserve unrelated or user-owned changes. Do not assume a local `main` or cached remote ref describes the deployed site.
3. State the intended file scope. Separate frontend presentation from generated data, canonical DB, local agents and deployment operations.
4. Work on your own task branch, created from the latest `origin/lab`, in your own worktree (see Lab-first lifecycle for the only exceptions). Never change `main`, merge to it, deploy production or force push without explicit owner authorization. Do not reset or rebase over pushed or generated-data commits.

## Git / Multi-Agent Session Protocol

### Branches

- `main` is production. A push or merge to `main` deploys https://babdoduk.vercel.app through Vercel's Git integration. Agents never modify `main` without explicit owner authorization, and a full `lab` → `main` merge is never the default.
- `lab` is the integration/staging branch (https://babdoduk-lab.vercel.app): the production baseline plus intentional lab-only experiments. It is not a general scratch branch; agents do not normally develop directly on it. Integrating a task branch into `lab` is a separate, authorized step.
- Task branches are `agent/claude/<task>`, `agent/codex/<task>`, `agent/cursor/<task>` (or `agent/<tool>/<task>`). Each starts from the latest `origin/lab`. A task that will end in production still starts there; only an owner-authorized bypass listed under Lab-first lifecycle starts from `origin/main`.
- Release branches are `release/<name>`, started from the latest `origin/main`. They carry only commits already deployed and owner-approved on lab (by `git cherry-pick -x`), never `lab` as a whole, and are merged only with explicit owner approval. The canonical procedure is `release-babdoduk`.

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
- Shared navigation and footer markup comes from `shared/nav.html` and `shared/footer.html`: edit those and run `python scripts/sync_site_chrome.py`; never hand-edit a page's copy. The same holds for the shared labels in `data/content/labels.json` (free-food types, sources, cafeterias, the picker's cuisines, magazine lanes): the sync writes them into the pages' translation tables and the marked `// @labels:` blocks of scripts, and the pipeline reads them through `scripts/content_labels.py`. So does the page content: `event.html` and `history.html` are written from `data/content/events.json` and `history.json`. Their styles belong to `css/site.css` only. Every page's Korean and English text is in `i18n/ko.json` and `i18n/en.json`, one entry per key in both files: the sync writes each page's table from the key families it shows (`PAGES` in `scripts/sync_site_chrome.py`), and `js/site.js` is the one language switch, scroll bar and "more" menu. Some component styles are still duplicated per page. Inspect every consumer and edit scoped locations; never run a blind global rewrite.
- Do not manually edit generated `data/magazine/`, `data/kaist-menu/` or `data/ggongbab/latest.json` to make UI tests pass. Preserve their schemas (`schemas/`, `docs/DATA.md`), validators, provenance and branch publication rules. `data/foods/` (the picker's dish catalog), `data/content/` (shared labels, news and events, history), `data/food-log.json` and `inputs/ggongbab/` (`manual.json`, the public `food-news.json`) are authored data, not generated output: edit them through a normal commit and keep `python scripts/validate_content.py --only authored` passing; `inputs/` is never deployed.
- Keep fixture and localhost preview behavior separate from normal routes. `lab-ggongbab.html` is `noindex` but that is not access control. The experiment pages (`lab.html`, `lab-ggongbab.html`, `food.html`) and their data (`data/food-log.json`, `calendar.ics`) are lab-only: `vercel.json` answers 404 for them on every host but babdoduk-lab.vercel.app, so production never serves them while both branches keep the same files. Never let preview, raw mail, credentials or private DB content enter public HTML or JSON.
- Preserve keyboard access, visible focus, status announcements, Korean/English copy, long-text wrapping, reduced-motion behavior and the existing scrollbar design. A visual task must not relax an assertion, publication rule or security gate.
- Keep localStorage keys and existing user data readable. Do not silently replace user-selected filters or food records.
- Distinguish verified facts, inferred states, authored material, generated fallback and suggestions in copy and metadata.
- Do not log or commit passwords, API tokens, JSESSIONID, browser profiles, unredacted mail, raw Portal IDs or private source URLs.

## Protected boundaries and explicit authorization

Ask for a task specifically targeting these before changing them: `supabase/migrations/`, RLS, grants, Realtime publication or RPC; `scripts/ggongbab/` collectors, parsers, dedup, sanitizer, validator and exporter, and the public JSON contract; Dooray and Portal agent/session behavior; Windows scheduled workers; GitHub Actions workflows and schedules (including repairing `.github/workflows/ggongbab-refresh.yml`); secret/configuration deployment; generated JSON schema; live authentication or live collector runs; `main` and production deployment. A presentation task does not authorize any of these.

Portal notice detail GET (`/wz/api/board/recents/{post_id}`) stays blocked, as do authentication replay and credential or OTP/MFA automation. Manual KAIST SSO/MFA remains human work: no agent or worker stores, types or replays a password, OTP, cookie or session token, or approves an MFA request. Lab-only / not promoted to production in the current main baseline (owner decision 2026-10-29): the resident ops may *start* a KAIST SSO Easy Login in the Ops Chrome while a login latch is set (click the portal's login button, then Easy Login's Login with the remembered ID already filled in), read the two-digit verification code and send only that code to the owner's Telegram; the owner approves on their own phone. It never types into a field or uses ID/PW Login, stops on any unexpected page, never logs or stores the code, and is rate-limited (`scripts/ggongbab/easy_login.py`, off unless `.local/easy-login.json` enables it; documented on the `lab` branch in `docs/PORTAL_EASY_LOGIN_ASSIST.md`). The cloud Portal collector on `main` is disabled. Lab-only / not promoted to production in the current main baseline: a Portal LIST-only session poller that may call only the pinned recent-post LIST GET, whose titles are only a Stage A signal (documented on the `lab` branch in `docs/PORTAL_LIST_POLLER.md`).

Dooray Radar mail reading (owner decision 2026-10-14, after two events were missed): the Radar opens every new mail, unread ones too, and reads its body, attachment text and same-host poster images; it marks an opened unread mail unread again with the web app's own call, and if that fails it stops opening unread mail until an operator reviews it. It sends only GETs of that mail plus that one restore POST, never fetches third-party images, never prints or stores mail text outside the private collection task, and still requires the verified read-state field (missing or unknown state fails closed). See `scripts/ggongbab/web/mail_detail.py`, `docs/GGONGBAB_DISCOVERY.md` and their synthetic tests. Other Dooray body use (the legacy agent) still requires explicitly already-read rows (`scripts/ggongbab/web/calibrate.py`, `docs/GGONGBAB_PREVIEW.md`).

On `main`, public pages read only the validated static snapshot `data/ggongbab/latest.json` (plus the other generated JSON files); private canonical tables and backend credentials stay outside the frontend, and the browser holds no Supabase configuration. Lab-only / not promoted to production in the current main baseline: an allowlisted public DB projection read by the browser through Supabase SELECT/Realtime with a static fallback (documented on the `lab` branch in `docs/GGONGBAB_PUBLIC_FEED.md` and `docs/GGONGBAB_REALTIME.md`). Promoting it needs its own authorized task covering migrations, backend publication and frontend together. Since 2026-10-13 (owner-authorized) the backend publication alone runs on `main`: the scheduled ggongbab-refresh workflow synchronizes the projection after publishing the snapshot (`scripts/sync_public_feed.py`, the snapshot's own selection); the browser read stays lab-only. Lab-only / not promoted to production in the current main baseline: the 먹방 월드컵 reads anonymous aggregate pick counts and records a finished game through the validating RPC `worldcup_record_game` (migration 005, documented on the `lab` branch in `docs/WORLDCUP_STATS.md`).

## Verification by change type

Run focused tests first, then the relevant full gate before completion. Do not use a live Dooray/Portal account or Supabase project as a synthetic test fixture.

| Change | Required checks |
| --- | --- |
| Documentation only | Check links and facts against current code/docs on the same branch; review diff and status |
| General frontend | `python -m pytest tests -q`, `python scripts/validate_content.py`, `python scripts/sync_site_chrome.py --check`, `python scripts/check_site_ui.py` (site guardian and chrome visual baselines; baselines change only with owner approval, `docs/VISUAL_BASELINES.md`); inspect mobile/tablet/desktop and keyboard behavior |
| Ggongbab or menu frontend | General frontend checks plus `python scripts/check_ggongbab_ui.py`; preserve the fixture clock only in fixture mode and fixed-clock scenarios, the initial all-upcoming filter, saved filters, public eligibility, Radar and featured |
| Pipeline or contract, explicitly authorized | Contract-specific synthetic tests plus full suite and content validator; review private/public field boundaries and failure exits |
| Generated-data workflow, explicitly authorized | Validate only selected generated paths and publication branch behavior; never merge feature code through `publish_generated.py` |

Checks must not depend on the wall clock: a scenario that needs "today" fixes the page clock and derives its synthetic data from the same reference time. Report every gate's first result, including failures, and never weaken an assertion to pass (procedure: `verify-babdoduk`). Tests are evidence for the code under test, not proof that external services, production deployment or data freshness are healthy. State what was not tested.

## Handoff

Report changed files, the user-visible result, tests and counts, remaining risks, remote movement, and the branch with its exact commit and push state (procedure: `handoff`). If the task is interrupted, leave a concise continuation prompt with current SHA, worktree changes, completed phase, next phase, open owner decisions and commands needed to resume. Never leave a half-finished unreviewed mutation disguised as complete.
