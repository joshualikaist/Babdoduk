# Babdoduk architecture and change boundaries

Status: `main` production baseline, as prepared for the Phase 10B release (`release/product-refresh-2026-09`, based on `origin/main` 1331489, 2026-09-24). “In code” does not establish that a config is active, that a deployment serves it or that its data is fresh. Sections labelled **Lab-only / not promoted to production in the current main baseline** describe work that exists only on the `lab` branch.

## Production system map (`main`)

```text
EXTERNAL SERVICE                 GENERATED DATA                     FRONTEND (static, Vercel project babdoduk)
RSS / YouTube ── magazine refresh ──> data/magazine/ ────────────> mukbang.html, index.html
KAIST official cafeteria HTML ──────> data/kaist-menu/ ──────────> ggongbab.html, mukbang.html, index.html

Dooray project / KAIST public notices / authored manual input / mail-archive backfill
       │
       ▼
Python collectors → private raw item and attachments → PII sanitizer → rules/AI
       → deterministic validator → dedup → Supabase canonical events (migrations 001–002)
                                                │
                  exporter.build_payload (explicit food, published, not under review,
                  confidence, expiry, horizon) → validate → data/ggongbab/latest.json
                  exporter.build_archive (same eligibility, expired at the same clock,
                  previously listed, last 30 days, no sign-up fields) → validate
                                                   → data/ggongbab/archive/index.json
                                                │
                              static fetch only ├─> ggongbab.html (hub: live list, then past listings)
                                                └─> index.html (home summary, live only)

LOCAL FRONTEND STATE
data/foods/catalog.json + 7 packs → food engine → picker (mukbang.html#what) → optional slot animation
food.html + authored data/food-log.json + browser-local entries/preferences/filters

OPERATIONS
GitHub Actions content-refresh → validate_content.py → allowlisted generated paths to lab and main
Local Dooray agent (resident browser, human SSO) → Dooray tasks for the collectors
```

The browser holds no database configuration: every public page reads only static files served from the same site.

## Lab-only architecture (not promoted to production in the current main baseline)

These exist on the `lab` branch with their own documents there (`docs/GGONGBAB_PUBLIC_FEED.md`, `docs/GGONGBAB_REALTIME.md`, `docs/PORTAL_LIST_POLLER.md`, `docs/GGONGBAB_RESIDENT_OPS.md`). They are recorded here so they are not mistaken for production behavior:

```text
Supabase canonical events → shared public selection (exporter.select_public_events) + public sanitizer
       ├─> data/ggongbab/latest.json ─────────────> static fallback
       └─> 22-column public projection (migration 004) ─> browser SELECT + Realtime
                                                           (js/ggongbab-public-feed.js,
                                                            js/ggongbab-public-config.js)
Pipeline heartbeat and ingest-failure reporting (migration 003)
Human Portal SSO/MFA → dedicated Chrome → in-memory session → exact LIST-only poller
       → private local checkpoint/pending + operational heartbeat
       [no Portal detail GET, event approval, Dooray task or public feed publication]
Windows resident workers, watchdog and bounded recovery (scripts/windows/*)
```

On lab the static file and the DB projection are written in sequence, not atomically, so a failed projection sync can leave them out of step. Promoting any of this needs a dedicated, owner-authorized task that applies the migrations and ships backend and frontend together; a UI release must not carry it.

## Static frontend and local state

Eight public HTML files are the route entry points: `index.html`, `ggongbab.html`, `lab-ggongbab.html`, `mukbang.html`, `food.html`, `event.html`, `history.html`, `lab.html`. CSS and JavaScript are loaded without a build step; `css/site.css` owns the shared navigation, footer, tokens and scrollbar. Vercel serves the static files; see “Environment and deployment”.

`js/ggongbab.js` renders normal, fixture and localhost preview modes; public routes cannot read the private preview, and normal mode fetches only `data/ggongbab/latest.json`. `js/ggongbab-select.js` holds the client-side eligibility repeat (explicit food, not under review, not ended) shared by the hub and the home summary. `js/kaist-menu.js` exports the KST date and stale rules used by the hub, the magazine summary and `js/home.js`; the home summary reads the same static snapshots as the hub and names their last publication time. `js/food-engine.js` ranks built catalog dishes; `js/food-picker.js` runs the decision UI; `js/eat-slot.js` animates a previously selected result. Filter, preference, language and food-log state use localStorage. Repeated inline page translation code remains a maintenance concern.

## Generated and authored data

| Data | Writer/owner | Consumer and failure behavior |
| --- | --- | --- |
| `data/magazine/index.json`, dated and latest editions | `scripts/refresh_magazine.py` using RSS/YouTube and authored fallback | Magazine and home read edition data; fallback is not evidence of a fetched story |
| `data/kaist-menu/` | `scripts/refresh_kaist_menu.py` parsing the official KAIST page without AI | Hub, magazine and home; zero usable restaurants keeps prior files, so clients must check the date |
| `data/ggongbab/latest.json` | Approved export in `scripts/refresh_ggongbab.py` | Hub and home; validation precedes the final write and a failure keeps the previous file |
| `data/ggongbab/archive/index.json` | Same export, same clock (past listings, 30 days) | Hub only, fetched separately; a failed archive keeps the previous file without blocking `latest.json`, and a failed fetch leaves the live feed untouched |
| `data/foods/catalog.json`, 7 packs | `scripts/build_foods.py` and `scripts/food_expand.py` | Browser-only dish suggestion catalog, not restaurant inventory |
| `data/food-log.json` | Human-authored | `food.html` combines it with browser-local entries by date and labels each day's source |
| `data/ggongbab/manual.json` | Human-authored collector input | Private pipeline input, excluded from generated-data mirroring |

`.github/workflows/magazine-daily.yml` (content-refresh) refreshes magazine and cafeteria data on schedules and manually. `.github/workflows/ggongbab-refresh.yml` refreshes the approved free-food output on a 30-minute schedule (cron `*/30 * * * *`, UTC; a scheduled run is always `full`) and by manual dispatch in five modes, of which only `export-only` and `full` can publish. GitHub rejected the file as invalid YAML until the 2026-09-25 repair; the schedule was re-enabled on 2026-09-26 after the manual `check`, `dry-run` and `review-report` runs passed on main. A `full` run collects sources, calls OpenAI, writes Supabase and pushes `data/ggongbab/` to lab and main; the publisher skips the commit when only `generatedAt` changed. `scripts/publish_generated.py` mirrors only allowlisted generated paths using detached worktrees; it is not a feature-code merge or a generic deployment command. Rebase behavior inside that operational publisher is specific to its isolated generated-data commits and must not be copied into manual branch handling.

## Free-food canonical and public boundaries (production)

`scripts/ggongbab/pipeline.py` collects from Dooray, public KAIST notices, manual input and mail-archive backfill; the Portal collector is disabled (`enabled()` returns false). Private raw items go through PII sanitization, rule processing, optional AI structured extraction, deterministic validation, review flags and deduplication before canonical storage in Supabase. The AI result is a candidate; validators and publication policy decide what can be shown.

`scripts/ggongbab/exporter.py` `build_payload(..., food_only=True)` publishes only rows that are `published`, not under review, at or above the confidence threshold, not expired and within the export horizon, with food explicitly provided. `public_event` copies only public fields and keeps source URLs only for public web sources (KAIST notices, manual entries); Dooray/task links, raw content and sender details are never exported. `scripts/refresh_ggongbab.py` validates the staged file before replacing `data/ggongbab/latest.json`. The browser never queries the canonical database.

Past listings reuse that policy rather than restating it: `build_archive` takes rows that `publication_eligible` accepts and `is_expired` drops at the same `now`, ended within 30 days, and only if their id was in the previously published `latest.json` or archive, so a backfilled event that ended before any export is never presented as a past listing. Records are `public_event` without `registration` and `confidence`. An archived row means "was a public listing and has ended", not that the event took place. No Supabase schema change; the read is a filtered `events` SELECT (`recent_published_events`). Contract and validation: `docs/GGONGBAB_PAGE.md` §11.

## Local agents and external services

Dooray: `scripts/dooray_web_agent.py` and `scripts/ggongbab/web/` manage resident-browser use, calibration, read-state verification and task writing. A verified read-state field and at least two explicitly read rows are required for detail calibration; unknown/unread rows cannot be fetched for verification. `--run --read-state read` fails closed when the field is unavailable. Backfill/preview behavior is separately documented in `docs/GGONGBAB_PREVIEW.md`.

Portal: `main` contains the earlier Portal observation, discovery and queue diagnostics (`scripts/portal_web_agent.py`, `scripts/ggongbab/portal_*.py`) described in `README.md`; the cloud collector stays disabled and notice detail replay stays blocked. The LIST-only session poller and the Windows resident workers are lab-only (see above). Authenticated browser profiles and `.local/` are sensitive local material.

## Environment and deployment

`main` is production and `lab` is integration/staging. Vercel's Git integration is active for both projects: GitHub deployment records from 2026-09-23 show a push to `main` creating a Production deployment of `babdoduk` (https://babdoduk.vercel.app), a push to `lab` creating a Production deployment of `babdoduk-lab`, and each project building the other's branch as a Preview. Treat merging to `main` as a production deploy. Generated content is pushed to both branches without promoting application code. Branch, worktree and release rules are in `AGENTS.md` (“Git / Multi-Agent Session Protocol”) and `docs/DEPLOYMENT_AND_BRANCHES.md`.

No tracked Web Push/service worker implementation exists. Do not add browser notification permission as a side effect of a redesign.

## Failure, tests and observability

- Data can be old when a collection run fails or does not run; use payload dates and explicit stale UI rather than silently calling old data “today”.
- Export preparation errors keep the previous `latest.json`. One healthy-looking page does not show that collection is current; the home summary shows the snapshot's last publication time.
- Dooray unknown read state blocks body access. Validator review states do not appear in the public feed.
- `tests/ggongbab/` covers parsers, safety and export contracts with synthetic fixtures. `tests/test_kaist_menu.py` covers official HTML parsing. `tests/test_site_ui.py`, `tests/test_product_ui.py`, `scripts/check_site_ui.py` and `scripts/check_ggongbab_ui.py` cover local UI behavior; scenarios that need “today” fix the page clock and derive their synthetic data from the same reference time. `scripts/validate_content.py` validates generated outputs. None of these proves a production service is live.

## Change boundaries

| Requested change | Expected files | Protected unless separately authorized |
| --- | --- | --- |
| Home/magazine appearance | `index.html`, `mukbang.html`, scoped CSS and UI checks | Collectors, Supabase, generated JSON, Portal/Dooray, workflow schedules |
| 오늘의 꽁밥 (free-food hub) presentation | `ggongbab.html`, `lab-ggongbab.html`, scoped JS/CSS and UI checks | Selection rules, source authentication, publication schema and backend writes |
| Picker presentation | Existing picker/slot entry and styles | Dish data meaning, hard safety claims, DB/profile introduction |
| Event/history/food-log content | Authored HTML and explicitly owned input | Claiming unverified activity occurred, discarding local entries |
| Data or security contract | Targeted backend area and synthetic tests after explicit scope | Unrelated UI and production deployment |
| Promoting a lab-only system | Dedicated release plan with migrations, backend and frontend together | Bundling it into a UI release |

The Portal notice detail endpoint `/wz/api/board/recents/{post_id}` remains blocked because past observation found a potential view-count side effect. New Ara's use of that endpoint is not evidence of safety here. Authentication replay, credential and OTP/MFA automation are outside this architecture.
