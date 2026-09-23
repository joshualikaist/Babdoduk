# Phase 2B: public browser feed (lab only)

This change does not deploy, run migrations, mutate live data, or change Portal,
Dooray, Windows OPS, canonical approval or private-table security. Portal detail
GET remains blocked. Phase 2A was manually activated by the operator on
2026-09-23: public projection and static snapshot each contained four events.
Counts can subsequently change; that observation is not a perpetual invariant.

## Static-site audit and configuration

The two HTML entry points load ordinary scripts at the end of the body. There is
no package.json, SPA bundle/build pipeline, tracked vercel.json or repository CSP/
HTTP-header configuration. Fonts are already externally loaded; application
scripts are local. `.vercelignore` excludes `.env`, `.local` and local Vercel state.
No server environment expansion is added, and private local files are never read
by this feature. Platform/dashboard headers were not inspected or changed.

Load order: existing menu script, `js/ggongbab-public-config.js`,
`js/ggongbab-public-feed.js`, existing renderer `js/ggongbab.js`.
The committed config is intentionally empty, so the site works with JSON without
configuration. To enable this on an operator-authorized lab site:

1. In the Supabase dashboard obtain the project URL and **browser publishable
   key**, or the legacy **anon** key. Do not use any backend/privileged key.
2. Edit only the two empty strings in `js/ggongbab-public-config.js`:
   `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY`. Both values are intentionally
   public to every visitor. Do this locally/in the authorized lab artifact;
   never paste credentials into chat. Do not copy `.env` into frontend output.
3. A dashboard environment variable alone does **not** change a static file.
   There is no automatic build substitution. Review/commit the two public values
   separately if desired, or supply the file in an authorized artifact workflow.
   This implementation commits neither project identifiers nor real keys.
4. Only an HTTPS origin (no credentials/path/query/fragment) and a publishable
   prefix or JWT whose role is `anon` pass the accidental-misconfiguration guard.
   This is not JWT signature verification; database grants/RLS are authoritative.
   Clear either value to deliberately use JSON only.

Only in normal, configured mode is the SDK loaded dynamically:
`https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.116.0/dist/umd/supabase.js`.
Exact version and SHA-384 SRI are pinned. It is not vendored or bundled; there is
no new build stack. The 8-second load deadline, blocked CDN, integrity mismatch or
unsupported browser causes fallback. A future CSP must permit the exact CDN
script, the configured project's HTTPS/WSS connections and the site's existing
scripts/fonts; no wildcard security-header relaxation is introduced here.
The SDK uses public schema with auth persistence, auto-refresh and URL session
detection disabled. No login, user-session import or browser storage is required.
See official [installation](https://supabase.com/docs/reference/javascript/installing)
and [client initialization](https://supabase.com/docs/reference/javascript/initializing).

## Read contract and event mapping

The only queried/subscribed table is `public.ggongbab_public_events`.
Every SELECT names these exact 22 columns (never `*`):

```text
id,title,summary,start_at,end_at,date_text,time_text,location_name,building,room,food_provided,food_type,food_description,organizer,eligibility,registration_required,registration_deadline,registration_url,source_types,confidence,content_revision,updated_at
```

Order is ascending `start_at`, then ascending `id`. Requests use ranges of 500,
continuing by the number actually received until an **empty** page, so a lower
server row cap does not truncate the set. An empty initial result is an
authoritative empty feed, not a failure. Partial/invalid/error results never
replace the last good collection. Whole reconciliation has a 12-second deadline.

`mapRow()` matches `public_feed.to_snapshot_event()`, including KST second-level
timestamps/nulls, nested location/food/registration, tri-state strings and fixed
known source labels. It does not copy extra row fields, query source metadata or
create source links. The existing renderer retains escaping, safeHref protocols,
public-food/review checks, date sorting, filters, radar and featured cards.
Revisions stay internal; DB mode has no global `generatedAt`/updated line.
Snapshot mode retains the real snapshot's timestamp.

## Authority, Realtime and recovery

One controller owns a normalized ID-keyed collection and publishes it to the
existing renderer; fetch callbacks and subscription callbacks never independently
own UI state. States are `loading`, `db-live`, `snapshot-fallback`, `reconnecting`.

1. Create one channel with `postgres_changes`, event `*`, schema `public`, table
   `ggongbab_public_events`; no other table, broadcast, presence or write API.
2. Wait for `SUBSCRIBED`, then perform the authoritative full SELECT. Before
   confirmation/throughout SELECT, changes invalidate that in-flight snapshot.
3. If a change arrives during pagination/SELECT, repeat the full SELECT (at most
   five rounds within the deadline). Do not replay an older buffered update over
   a newer SELECT result. Publish only a completed quiet read. Constant churn
   fails to fallback/retry instead of publishing a partial mixed set.
4. Live INSERT/UPDATE upserts/replaces by ID. Same ID+`content_revision` is a
   no-op, including updated_at-only changes. DELETE uses only `old.id`; default
   replica identity is sufficient. Render recalculates cards, radar, badges,
   date headings and featured event without resetting filters, language or tab.
5. Errors/closed/timeouts invalidate callbacks, abort SELECT, retire the old
   channel and disconnect its transport before replacement. Delayed results from
   retired attempts cannot overwrite current state. Confirmed reconnect always
   performs a fresh full SELECT; offline-deleted IDs disappear.
6. Backoff with downward jitter: nominal 1, 2, 4, 8, 16, then 30 seconds capped;
   actual delay is 80–100% of nominal. No duplicate channels or tight loops.
   Every 60 seconds while visible, reconcile again to heal silently missed
   changes. A separate 60-second renderer tick applies expiry even with no DB
   deletion. Both stop when hidden/pagehide; visibility/pageshow resume with
   fresh reconciliation, including browser back-forward cache restoration.

If config/client/network/SELECT/subscription/reconciliation fails, attempt
`data/ggongbab/latest.json` with no-store and an 8-second deadline. Pending
requests are aborted on lifecycle/attempt retirement when supported.
With no successful DB collection,
render that snapshot and retry DB when configured. A later successful DB SELECT
**replaces** the snapshot, never merges stale rows. If a DB collection was already
selected, preserve it during the outage (including a valid empty collection);
do not resurrect older snapshot rows. Snapshot is fetched as fallback, but last
good DB data remains authoritative while reconnecting. If neither source has
ever loaded, the existing nontechnical retry/error UI appears; cafeteria remains
independent. There is no technical connection panel and no value-bearing logging.

Realtime is not durable history. See official
[Postgres Changes](https://supabase.com/docs/guides/realtime/postgres-changes),
[subscription statuses](https://supabase.com/docs/reference/javascript/subscribe)
and [channel removal](https://supabase.com/docs/reference/javascript/removechannel).

## Isolation and privacy

Lab fixture uses its existing synthetic events. Localhost preview uses only
`.local/ggongbab-preview.json`; non-local preview remains blocked. Public-page
fixture/preview query parameters still cannot unlock lab data: they use public
JSON only. **All** `fixture=1`/`preview=1` paths skip client creation, SDK load and
subscription even with a valid public config. Rendering/language/tab changes
never open a connection. No browser DB writes or RPC are used. No private table,
Portal state, cookie, backend key, source ID or account identifier is requested,
stored or logged. Existing backend sanitization and database grants remain the
security boundary; public config cannot compensate for misconfigured RLS.

## Manual live acceptance (operator only, not run by automated tests)

Do not re-apply migration 004 or mutate canonical/live rows for this procedure.
Do not include public project/key values in screenshots/reports shared here.

1. Configure the two browser-public values in an authorized lab artifact. Open
   normal `lab-ggongbab.html`. In DevTools Network confirm SELECT's table,
   22-column allowlist and start_at/id order. Compare result IDs/count/cards
   with `latest.json` (operator's Sep 23 baseline was four; account for later
   expiry/publication). Confirm the Realtime join receives `SUBSCRIBED`/a
   successful join reply for this public table only. There is no global snapshot
   updated line in DB mode. Do not copy request headers/keys into a report.
2. Disconnect the network using DevTools. Current cards must stay visible.
   Restore network and wait up to the capped backoff plus SELECT deadline;
   verify a full re-SELECT and only one active channel. No row mutation needed.
3. Disable public config in the local lab artifact (or block the CDN before a
   fresh page load). Verify JSON cards and its real generated timestamp. Restore
   config/reload; DB replaces JSON. Test public JSON empty and failure cases
   only through browser request overrides, not live data edits.
4. Open fixture and localhost preview; Network must have zero DB/WSS/CDN SDK
   requests and no Supabase client creation. Test cafeteria, filters and language.
5. INSERT/UPDATE/DELETE UI mechanics are covered with synthetic rows. There is
   no new safe live mutation mechanism; any later real mutation acceptance needs
   separate operator approval and an isolated disposable test project.

### Non-mutating public-role permission acceptance

Browser-safe SELECT above tests actual RLS read access. For write-denial evidence
without issuing any live mutation, an operator can run the following **read-only
catalog query** in the SQL editor; it does not call the RPC or alter permissions.
Expected for each role: can_select=true and the other four booleans=false.
This is catalog evidence, not a claim of an actual browser write attempt.

```sql
SELECT role_name,
  has_table_privilege(role_name, 'public.ggongbab_public_events', 'SELECT') AS can_select,
  has_table_privilege(role_name, 'public.ggongbab_public_events', 'INSERT') AS can_insert,
  has_table_privilege(role_name, 'public.ggongbab_public_events', 'UPDATE') AS can_update,
  has_table_privilege(role_name, 'public.ggongbab_public_events', 'DELETE') AS can_delete,
  has_function_privilege(role_name,
    'public.ggongbab_replace_public_feed(bigint,jsonb)', 'EXECUTE') AS can_call_rpc
FROM (VALUES ('anon'), ('authenticated')) AS roles(role_name);
```

No privileged key is used in the browser or acceptance code. If active HTTP
write-rejection checks are desired, use a separately approved disposable test
project with the same migration and a browser-public key: SELECT must succeed;
INSERT/UPDATE/DELETE and replacement RPC must fail with permission denial.
Do not test writes/RPC against these four live rows, even with invalid IDs: a
misconfigured replacement RPC could remove the entire projection. No live write
acceptance script is shipped or automatically executed.

## Tests and limits

`node --test tests/ggongbab/public_feed.test.cjs` uses only Node built-ins and
synthetic clients/timers. `test_frontend_public_feed.py` also runs that suite,
compares mapping to Python, checks the source boundary and drives real Chromium
with all requests intercepted (synthetic client, no external services). Node and
the same Playwright Chrome used by the existing UI checker must be installed.
Run the complete regression suite:

```text
python -m pytest tests -q
python scripts/validate_content.py
python scripts/check_ggongbab_ui.py
```

Existing UI checks remain intact. The dedicated new integration tests use their
own synthetic clock; the existing UI checker's fixture-only clock policy and
normal/preview/production-like route clocks are unchanged.

No live Realtime latency/permissions acceptance was executed by this change.
With a configured healthy connection, latency is one SELECT on load and network
delivery plus rendering on live changes; no measured SLA is claimed. Missed
messages self-heal on the 60-second reconcile. Offline recovery adds up to
30 seconds backoff plus connection/SELECT time, or immediate retry on visibility
return. Actual meal discovery still depends on ingestion/publication cadence.
The capped paginated read is not a database transaction snapshot; delivered
changes invalidate it, and periodic/reconnect reads heal missed/delayed messages.
CDN/network/RLS/publication availability and correct operator public config remain
external dependencies. No config is enabled, deployment performed, migration
executed or Web Push added by committing this implementation.
