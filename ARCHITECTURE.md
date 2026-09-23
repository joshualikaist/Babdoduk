# Babdoduk architecture and change boundaries

Status: lab repository implementation as inspected 2026-09-23. “In code” does not establish that a config is active or that production serves it. `main`, lab, generated-data pushes, database activation and live external services must be checked independently before any release claim.

## System map

```text
EXTERNAL SERVICE                 GENERATED DATA                     FRONTEND (static Vercel)
RSS / YouTube ── magazine refresh ──> data/magazine/ ────────────> mukbang.html
KAIST official cafeteria HTML ──────> data/kaist-menu/ ──────────> ggongbab.html, mukbang.html

Dooray project / KAIST public notices / authored manual input
       │
       ▼
Python collectors → private raw item and attachments → PII sanitizer → rules/AI
       → deterministic validator → dedup → Supabase canonical events (BACKEND / DATA)
                                                │
                              common approved publication selection
                              ├─> data/ggongbab/latest.json ────> public feed fallback
                              └─> 22-column public projection ──> SELECT + Realtime

LOCAL AGENT (separate Stage A)
Human Portal SSO/MFA → dedicated Chrome → in-memory JSESSIONID → exact LIST poller
       → private local metadata checkpoint/pending + operational heartbeat
       [no Portal detail GET, event approval, Dooray task or public feed publication]

LOCAL FRONTEND STATE
data/foods/catalog.json + 7 packs → food engine → picker → optional slot animation
food.html + authored food-log JSON + browser-local entries/preferences/filters

OPERATIONS
GitHub Actions → validate_content.py → allowlisted generated paths to lab/main
Windows resident workers and heartbeat → operator recovery, outside browser UI
```

## Static frontend and local state

Eight public HTML files are the route entry points: `index.html`, `ggongbab.html`, `lab-ggongbab.html`, `mukbang.html`, `food.html`, `event.html`, `history.html`, `lab.html`. CSS and JavaScript are loaded without a build step. Vercel serves the static files according to the branch/project setup documented in `docs/DEPLOYMENT_AND_BRANCHES.md`; that document is policy, not a live deployment check.

`js/ggongbab.js` renders normal, fixture and localhost preview modes; public routes cannot read the private preview. `js/kaist-menu.js` also has a separate magazine renderer. `js/food-engine.js` ranks built catalog dishes; `js/food-picker.js` runs the decision UI; `js/eat-slot.js` animates a previously selected result. Filter, preference, language and food-log state use localStorage. Repeated inline page translation/nav/footer code remains a maintenance concern.

## Generated and authored data

| Data | Writer/owner | Consumer and failure behavior |
| --- | --- | --- |
| `data/magazine/index.json`, dated and latest editions | `scripts/refresh_magazine.py` using RSS/YouTube and authored fallback | Magazine reads edition data; fallback is not evidence of a fetched story |
| `data/kaist-menu/` | `scripts/refresh_kaist_menu.py` parsing the official KAIST page without AI | Hub and magazine; zero usable restaurants keeps prior files, so clients must check the date |
| `data/ggongbab/latest.json` | Approved export in `scripts/refresh_ggongbab.py` | Public fallback; validation precedes final write |
| `data/foods/catalog.json`, 7 packs | `scripts/build_foods.py` and `scripts/food_expand.py` | Browser-only dish suggestion catalog, not restaurant inventory |
| `data/food-log.json` | Human-authored | `food.html` combines it with browser-local entries by date; ownership semantics are an open product decision |
| `data/ggongbab/manual.json` | Human-authored collector input | Private pipeline input, excluded from generated-data mirroring |

`.github/workflows/magazine-daily.yml` refreshes magazine and cafeteria data on schedules and manually. `.github/workflows/ggongbab-refresh.yml` refreshes the approved free-food output. `scripts/publish_generated.py` mirrors only allowlisted generated paths using detached worktrees; it is not a feature-code merge or a generic deployment command. Rebase behavior inside that operational publisher is specific to its isolated generated-data commits and must not be copied into manual branch handling.

## Free-food canonical and public boundaries

`scripts/ggongbab/pipeline.py` collects from Dooray, public KAIST notices and manual input; the cloud `PortalCollector` is disabled. Private raw items go through PII sanitization, rule processing, optional AI structured extraction, deterministic validation, review flags and deduplication before canonical storage in Supabase. The AI result is a candidate; validators and publication policy decide what can be shown.

`exporter.select_public_events` is the shared selection policy for the static snapshot and public DB projection. Publication requires `status=published`, explicit `needs_review=false`, confidence threshold, food explicitly provided for this feed, valid dates and expiry/horizon rules. Text and URLs pass a public sanitizer. `scripts/ggongbab/public_feed.py` maps only 20 content fields plus revision/update metadata to the 22-column projection defined in migration 004. Canonical/source identifiers, raw content, sender details and credentials cannot cross this boundary.

The backend prepares and validates both representations, writes the static snapshot, then calls the service-only replacement RPC. This is not an atomic transaction across filesystem and database. A failed RPC can leave a new valid snapshot and an older DB projection; the command reports failure. The public table permits browser SELECT but not browser writes; only that table enters Realtime. See `docs/GGONGBAB_PUBLIC_FEED.md` for the exact schema, privileges and synchronization contract.

In normal public mode, `js/ggongbab-public-feed.js` selects the allowlisted public columns and reconciles a subscribed feed; an outage can use the validated static JSON fallback. Realtime transport does not shorten the collection schedule and is not a durable snapshot. Fixture/preview modes do not open the live DB path. `docs/GGONGBAB_REALTIME.md` governs recovery and security details.

## Local agents and external services

Dooray: `scripts/dooray_web_agent.py` and `scripts/ggongbab/web/` manage resident-browser use, calibration, read-state verification and task writing. A verified read-state field and at least two explicitly read rows are required for detail calibration; unknown/unread rows cannot be fetched for verification. `--run --read-state read` fails closed when the field is unavailable. Backfill/preview behavior is separately documented in `docs/GGONGBAB_PREVIEW.md`.

Portal: `scripts/portal_web_agent.py`, `portal_session.py`, `portal_list_contract.py`, `portal_list_poller.py` reuse a human-authenticated dedicated browser session in an in-memory HTTP client. Only exact `https://portal.kaist.ac.kr/wz/api/board/recents` LIST GET is authorized. The poller observes public list metadata and a title-based Stage A candidate signal, keeps a pseudonymous local checkpoint/pending set and emits an operational heartbeat. It neither fetches notice details nor confirms food, creates Dooray tasks, invokes AI or publishes a public event. Authentication/redirect/schema failures stop closed and require operator recovery. No credentials, cookie or raw notice value belongs in a heartbeat or generated JSON. `scripts/ggongbab/collectors/portal.py` remains disabled in cloud Actions. See `docs/PORTAL_LIST_POLLER.md`.

Windows scheduled workers and resident ownership checks are documented in `docs/GGONGBAB_RESIDENT_OPS.md`; they depend on an interactive local user session and do not imply continuous collection while the PC is off. Authenticated browser profiles and `.local/` are sensitive local material.

## Environment and deployment separation

`lab` is development and experimentation; `main` is the production/reference branch in repository policy. The documented Vercel projects map to those branches, but a branch push alone is not proof of a live deployment. Generated content can be pushed to both branches without promoting application code. A future visual release must compare the actual diff and explicitly review other lab changes such as migrations, Realtime and resident operations before promoting anything to `main`.

No tracked Web Push/service worker implementation was found at the audit date. Realtime is DB change delivery, not a push permission feature. Do not add browser notification permission as a side effect of a redesign.

## Failure, tests and observability

- Data can be old when a collection run fails; use payload dates and explicit stale UI rather than silently calling old data “today”.
- Private-to-public preparation errors keep the previous file; a later projection sync error is non-green and needs reconciliation. Do not infer both sinks are current from one healthy-looking page.
- Portal authentication loss stops the LIST poller; the heartbeat reports operational status but never republishes notice values or resumes login automatically. LIST absence is not evidence of cancellation.
- Dooray unknown read state blocks body access. Validator review states do not appear in the public feed.
- `tests/ggongbab/` covers parsers, safety, contracts, projection, realtime and poller using synthetic fixtures. `tests/test_kaist_menu.py` covers official HTML parsing. `tests/test_site_ui.py`, `scripts/check_site_ui.py`, and `scripts/check_ggongbab_ui.py` cover local UI behavior. `scripts/validate_content.py` validates generated outputs. None of these proves a production service is live.

## Change boundaries

| Requested change | Expected files | Protected unless separately authorized |
| --- | --- | --- |
| Home/magazine appearance | `index.html`, `mukbang.html`, scoped CSS and UI checks | Collectors, Supabase, generated JSON, Portal/Dooray, workflow schedules |
| Today's food presentation | `ggongbab.html`, `lab-ggongbab.html`, scoped JS/CSS and UI checks | Selection rules, source authentication, publication schema and backend writes |
| Picker presentation | Existing picker/slot entry and styles | Dish data meaning, hard safety claims, DB/profile introduction |
| Event/history/food-log content | Authored HTML and explicitly owned input | Claiming unverified activity occurred, discarding local entries |
| Data or security contract | Targeted backend area and synthetic tests after explicit scope | Unrelated UI and production deployment |

The Portal notice detail endpoint `/wz/api/board/recents/{post_id}` remains blocked because past observation found a potential view-count side effect. New Ara's use of that endpoint is not evidence of safety here. Authentication replay, credential and OTP/MFA automation are outside this architecture.
