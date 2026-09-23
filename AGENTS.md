# Babdoduk agent working rules

This is the repository operating manual for human and AI changes. The current product direction is in `PRD.md`, UI contracts in `DESIGN_SYSTEM.md`, and implementation boundaries in `ARCHITECTURE.md`. Follow a direct user instruction when it explicitly changes the task scope; otherwise treat unresolved owner decisions as unresolved.

## Before starting

1. Read `PRD.md`, `DESIGN_SYSTEM.md`, `ARCHITECTURE.md`, `README.md`, and the `docs/` file governing the feature. Inspect the implementation and tests before planning a replacement.
2. Check branch, HEAD, remote tracking relationship and worktree state. Preserve unrelated or user-owned changes. Do not assume a local `main` or cached remote ref describes the deployed site.
3. State the intended file scope. Separate frontend presentation from generated data, canonical DB, local agents and deployment operations.
4. For a lab task, remain on `lab`. Never change `main`, merge to it, deploy production or force push without explicit user authorization. Fetch/merge normally when a task calls for syncing; do not reset or rebase over generated-data commits.

## Implementation discipline

- Reuse existing patterns before adding a new one. The static HTML/CSS/JS architecture needs a demonstrated problem before a build system or framework migration is proposed.
- Shared navigation, footer, language and component styles are duplicated today. Inspect every consumer and edit scoped locations; never run a blind global rewrite. `rebuild_index.py` and `patch_site.py` contain historical templates and must not be run without comparing their output against current pages.
- Do not manually edit generated `data/magazine/`, `data/kaist-menu/`, `data/ggongbab/latest.json` or `data/foods/` to make UI tests pass. Preserve their schemas, validators, provenance and branch publication rules. `data/food-log.json` and `data/ggongbab/manual.json` are authored inputs, not generated output.
- Keep fixture and localhost preview behavior separate from normal routes. `lab-ggongbab.html` is `noindex` but that is not access control. Never let preview, raw mail, credentials or private DB content enter public HTML or JSON.
- Preserve keyboard access, visible focus, status announcements, Korean/English copy, long-text wrapping, reduced-motion behavior and the existing scrollbar design. A visual task must not relax an assertion, publication rule or security gate.
- Keep localStorage keys and existing user data readable. Do not silently replace user-selected filters or food records.
- Distinguish verified facts, inferred states, authored material, generated fallback and suggestions in copy and metadata.
- Do not log or commit passwords, API tokens, JSESSIONID, browser profiles, unredacted mail, raw Portal IDs or private source URLs. A public Supabase read configuration is not a backend service key.

## Protected boundaries and explicit authorization

Ask for a task specifically targeting these before changing them: `supabase/migrations/`, RLS, grants, Realtime publication or RPC; `scripts/ggongbab/` collectors, parsers, dedup, sanitizer, validator, exporter and public feed contract; Dooray and Portal agent/session behavior; Windows scheduled workers; GitHub Actions schedules; secret/configuration deployment; generated JSON schema; live authentication or live collector runs; `main` and production deployment. A presentation task does not authorize any of these.

Portal's independent LIST poller can use only the pinned recent-post LIST GET. It does not authorize `/wz/api/board/recents/{post_id}`, notice detail GET, authentication replay or downstream publication. Manual KAIST SSO/MFA remains human work. A Portal LIST title is only a Stage A signal. See `docs/PORTAL_LIST_POLLER.md`.

Dooray body/detail use requires a verified read-state field and explicitly already-read rows. Missing or unknown state fails closed before body access. See `scripts/ggongbab/web/calibrate.py`, `docs/GGONGBAB_PREVIEW.md` and their synthetic tests.

The browser may read only the allowlisted public projection and static snapshot; private canonical tables and backend credentials stay outside the frontend. The two publication outputs share a policy but can become temporarily out of sync on partial failure. See `docs/GGONGBAB_PUBLIC_FEED.md` and `docs/GGONGBAB_REALTIME.md`.

## Verification by change type

Run focused tests first, then the relevant full gate before completion. Do not use a live Dooray/Portal account or Supabase project as a synthetic test fixture.

| Change | Required checks |
| --- | --- |
| Documentation only | Check links and facts against current code/docs; review diff and status |
| General frontend | `python -m pytest tests -q`, `python scripts/validate_content.py`, `python scripts/check_site_ui.py`; inspect mobile/tablet/desktop and keyboard behavior |
| Ggongbab or menu frontend | General frontend checks plus `python scripts/check_ggongbab_ui.py`; preserve fixture clock only in fixture mode, initial all-upcoming filter, saved filters, public eligibility, Radar and featured |
| Pipeline or contract, explicitly authorized | Contract-specific synthetic tests plus full suite and content validator; review private/public field boundaries and failure exits |
| Generated-data workflow, explicitly authorized | Validate only selected generated paths and publication branch behavior; never merge feature code through `publish_generated.py` |

Tests are evidence for the code under test, not proof that external services, production deployment or data freshness are healthy. State what was not tested.

## Handoff

Report changed files, the user-visible result, tests and counts, remaining risks, branch and exact commit/push state. If the task is interrupted, leave a concise continuation prompt with current SHA, worktree changes, completed phase, next phase, open owner decisions and commands needed to resume. Never leave a half-finished unreviewed mutation disguised as complete.
