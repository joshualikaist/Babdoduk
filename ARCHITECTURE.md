# Babdoduk architecture and release boundaries

Status: Phase 10B production-scoped candidate based on origin/main 13314895ef69d707b7ad886bf56c07e757edd385. This describes code in the candidate, not a deployed-service health claim.

## Frontend

Eight static HTML entry points load CSS/JS without a build framework. css/site.css owns common nav/footer, controls and warm scrollbars. Page-specific styles and repeated inline translations remain; do not regenerate pages from legacy templates.

- js/ggongbab.js reads data/ggongbab/latest.json once per load/retry. No direct Supabase SELECT, subscription, public-feed controller or Realtime activation is included.
- js/ggongbab-select.js repeats client eligibility/date rules for the hub and js/home.js: explicit food, no review flag, not ended, chronological presentation. Backend validators/export remain authoritative and unchanged.
- js/kaist-menu.js shares KST date/staleness semantics with home and the magazine summary.
- js/home.js reads static free-food/menu/magazine snapshots and labels publication time. Two page loads may see different published revisions; neither guarantees current collection.
- js/food-engine.js ranks catalog suggestions; js/food-picker.js presents them; js/eat-slot.js optionally animates the result. Choosing means preference, not eating.
- food.html overlays browser entries on the authored public log by date. A same-date browser row replaces the public row in the displayed combined totals. Provenance fields exist only in rendered copies; stored records are unchanged.
- lab.html retains its existing body and calendar.ics experiment. Both are already in main and publicly reachable. Shared chrome is not a public-surface redesign.

## Data flow

RSS/YouTube → existing magazine generator → data/magazine/ → magazine/home.
Official KAIST menu HTML → existing parser → data/kaist-menu/ → menu views/home.
Existing collector inputs → private sanitization/rules/AI → validation/dedup → canonical Supabase storage → approved static export → data/ggongbab/latest.json → public UI.

The release does not add a second public DB projection or browser DB access. Existing cloud PortalCollector stays disabled. New lab Portal LIST polling, Windows residency/heartbeat and public-feed/Realtime infrastructure are deliberately not promoted. Authentication, collectors, migrations and backend publication contracts are unchanged.

| Data | Owner | Consumer |
| --- | --- | --- |
| data/magazine/ | Existing refresh generator | Magazine and home |
| data/kaist-menu/ | Existing official-menu parser | Hub, magazine and home |
| data/ggongbab/latest.json | Existing approved export | Static hub and home |
| data/foods/ | Existing catalog generator | Local recommendation engine |
| data/food-log.json | Authored public log | Combined food-log presentation |
| data/ggongbab/manual.json | Authored collector input | Existing backend, not generated mirroring |
| calendar.ics | Existing tracked public calendar | lab.html |

## Privacy/data inventory (factual, not legal)

| Surface | State/destination | Retention and identity limits |
| --- | --- | --- |
| Language, filters, selected tab, menu favourites/meal | Browser localStorage | Until browser/user removes it; no server sync introduced |
| Picker preference/eaten feedback and food-log entries | Browser localStorage | May reveal personal food/expense history; no migration or upload introduced |
| Authored public food log/events/history/calendar | Tracked repository/static public hosting | Public, including lab.html/calendar.ics; future surface audit required |
| Static feed/menu/magazine/catalog requests | Same-site static hosting | Hosting request logs/retention are not established by code inspection |
| Google fonts and i.ytimg thumbnails | External requests when permitted by browser | Network metadata may reach those providers; retention not established |
| Social/map/registration/original-source links | External destination on activation | Destination practices are outside this repository's inventory |
| Private collectors, credentials and browser sessions | Existing backend/local operational environment | Never frontend JSON, heartbeat or public logs; not exercised in this release |

No new frontend account, authentication, analytics, cookie writer, Web Push, service worker, Supabase browser client or form submission endpoint is added. Browser-only input is not a promise about a shared device or hosting logs. No Privacy Policy or Terms are authored here.

## Git, automation and operations

main is production; lab is integration/staging. Each agent uses its own branch/worktree; release/<name> contains a reviewed production candidate. See AGENTS.md and docs/DEPLOYMENT_AND_BRANCHES.md.

Existing magazine-daily.yml declares magazine 10:00 KST and cafeteria 06:00/10:30/16:30 schedules. ggongbab-refresh.yml declares a 30-minute schedule, but the owner reports it broken. Declarations are not evidence of successful runs. Phase 10B neither repairs nor enables it.

publish_generated.py copies allowlisted generated paths to lab/main independently of feature development. The shared workflow concurrency group does not lock human/agent branches. Remote refs may advance during a session; stop automatic integration and inspect.

## Safety and verification

Do not invoke live collectors for UI QA. No Portal detail GET or authentication replay is authorized. Detail side effects must not be dismissed because another project uses the endpoint. Manual SSO/MFA stays human work. Secrets/private identifiers must never be printed or committed.

Fixtures, route interception and synthetic tests check UI and existing backend contracts offline. The fixture clock is limited to lab-ggongbab.html?fixture=1 without preview mode; normal and preview clocks remain native. Use the restricted loopback test server, not a directory-listing server.

Failure states distinguish unavailable, stale, empty and loading. Food eligibility/review gates remain unchanged. No generated file may be altered to make a check pass.

Required gates: full pytest, validate_content.py, check_site_ui.py and check_ggongbab_ui.py. The manifest records results and gaps. Vercel deployment, real screen-reader/Safari checks and external data freshness require separate approval/evidence.
