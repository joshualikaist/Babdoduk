# Phase 2A: sanitized public event projection

Implementation only; migration 004 has **not** been applied to a live project.
The static frontend still reads `data/ggongbab/latest.json`. There is no browser
Supabase integration, push/service worker, production deployment or new collector.

## Manual activation

Review and manually apply the **entire** SQL file, including BEGIN/COMMIT:

`supabase/migrations/004_ggongbab_public_feed.sql`

Apply after migrations 001–003 using the project database administrator. No
application command applies migrations. The migration deliberately aborts and
rolls back if `supabase_realtime` is absent, uses FOR ALL TABLES, or already includes
any of this pipeline's private tables. Review the existing publication manually
in that case; do not broadly enable replication or expose private tables.

After manual application, a separately authorized backend run of
`python scripts/refresh_ggongbab.py --export-only` reconciles both outputs without
collectors or AI. It needs the backend Supabase key; never put it in the browser.
This command is documented for the operator, not run during implementation.

Before 004 exists, lab publication runs fail non-green at public-feed preparation.
The previously written static snapshot remains available. There is no silent
optional-sync flag that would falsely claim the public projection was published.
Missing backend configuration also fails instead of silently substituting an
in-memory successful publication. Snapshot validation failures now exit 23 in
this combined publication path; they cannot masquerade as a successful sync.
Main/default-branch cron still runs its own code until a separate promotion;
pushing lab alone does not activate this feature in that production job.

## One publication policy

`exporter.select_public_events` is the common selection policy; `build_payload`
wraps it for the existing snapshot shape. The public synchronizer calls that same
builder with `food_only=True`, using one captured time for the whole preparation.

Only published, explicitly not-under-review events at the configured confidence
threshold, with explicit food confirmation, valid start/end ordering, within the
existing expiry grace and horizon, are selected. Nonfinite confidence and missing
review approval fail closed. The generic serializer still supports all three
food states for callers that explicitly do not request a free-food feed.

Both publication outputs use the same text/URL sanitizer and existing in-memory
snapshot validator. Invalid public representations abort preparation before any
projection write. The existing validator's additional constraints (including its
6-hour stale-feed ceiling) remain in force. A configured grace beyond that ceiling
can therefore cause validation failure; the synchronizer does not bypass it.

The Repository reads all relevant canonical rows with strict pagination instead
of silently truncating to 500 or dropping multi-day events that started over two
days ago. Invalid/non-JSON DB pages are failures, never interpreted as an empty
desired feed. Expiry/horizon selection is performed only by the common policy.

## Exact browser contract

`public.ggongbab_public_events` has these **22 columns only**:

```text
id, title, summary, start_at, end_at, date_text, time_text,
location_name, building, room, food_provided, food_type, food_description,
organizer, eligibility, registration_required, registration_deadline,
registration_url, source_types, confidence, content_revision, updated_at
```

`id` is the canonical event UUID, never a raw/source/Portal/Dooray identifier.
`start_at` is required; `end_at` and `registration_deadline` are nullable
timestamptz values. Other strings are non-null (empty means unstated).
`food_provided` is the **string** `"true"`, compatible with the current frontend;
`registration_required` is `"true"`, `"false"`, or `"unknown"`, never a boolean.
`confidence` is numeric, rounded as in the snapshot. `source_types` is a sorted,
deduplicated text array restricted to `dooray`, `dooray_mailbox`, `kaist_public`,
`manual`, `portal`. Labels come from a fixed mapping, not source-table names.

There are no foreign keys, private identifiers, arbitrary JSON/metadata, raw
text/HTML, sender/attachment data, source URLs, cookies or conflict details.
Text fields strip HTML markup, addresses, known secret/ID patterns and embedded
web links. Only separately checked URL fields may retain links. URL publication
is stricter for both paths: HTTPS only, no userinfo/port/query/fragment/encoding;
reviewed public form hosts or the public KAIST website paths only. Unknown hosts
are withheld. No Dooray/Portal authenticated URL is retained. No redirects are
followed to validate a public link. Adding hosts requires policy review.

Canonical publication approval is still necessary: string sanitization cannot
prove arbitrary prose contains no confidential meaning. `published` and explicit
`needs_review=false` are the trust boundary for approved event descriptions;
this feature does not declare all Portal titles public.

`public_feed.to_snapshot_event` is the tested Phase 2B mapping reference:
snake_case time fields map to `startAt`/`endAt` (converted to KST); location and
food fields become their existing nested objects; registration fields become
`registration`; source types become fixed `{type, name}` objects. The remaining
card properties keep their existing names. Source URLs are intentionally omitted.
No private lookup is required. Render strings as text, not HTML.

## Revisions and synchronization

`content_revision` is lowercase SHA-256 of UTF-8 canonical JSON of the 20
allowlisted public content fields. Keys are sorted, separators are `,` and `:`,
Unicode is unescaped and nonfinite numbers are rejected. Dates are normalized
to KST and source types sorted before hashing. `updated_at`, generation, raw
metadata, ingest timestamps and source ordering do not participate.

The synchronizer reads the private generation, prepares and validates the **entire**
desired public set, then calls one service-only `ggongbab_replace_public_feed`
RPC. The function locks the singleton generation row and rejects stale generations.
Within one transaction it validates input keys, upserts desired rows, deletes stale
rows, then advances the generation. A valid empty desired set removes stale rows.
An unchanged content revision does not update the public row or its `updated_at`,
avoiding artificial realtime updates. It still advances the private generation.

Any RPC/constraint failure rolls back the whole public replacement. Existing good
rows are not deleted before an unsuccessful replacement. Canonical writes are
separate and are never undone by projection failure. A concurrent stale preparation
fails explicitly; rerun export to read the current generation/canonical state.
An HTTP response lost after DB commit is an ambiguous failure, reported non-green;
rerunning is safe and does not create duplicate rows or revision churn.

This is atomic **projection replacement**, not a distributed transaction with
canonical ingestion or the filesystem. Canonical reads across REST pages can
observe concurrent edits. Generation checking prevents an older prepared sync
from overwriting a completed newer sync, but cannot serialize arbitrary direct
canonical edits. Reconciliation is still needed after such edits or failed runs.
The snapshot is written before the projection RPC, so a failed RPC leaves a usable
new snapshot and the previous DB projection; the command returns failure and does
not claim the two sinks are current. Preparation failures keep the previous file.

## All publication paths

`refresh_ggongbab.export` prepares both representations together and commits the
projection after snapshot validation/write. This covers the normal collector run,
`--export-only`, successful archive backfill, and the resident Dooray agent's
`--run-pipeline` subprocess. Sync failure exits 23 (`public_feed_sync`); the resident
wrapper maps it to pipeline failure, so it cannot emit a successful publish heartbeat.
Dry-run and local preview retain their in-memory/nonpublishing behavior.

If ingestion/backfill fails after partial canonical changes, the run is already
non-green and requires retry/reconciliation. Direct SQL moderation or deleting
canonical rows also requires `--export-only`. Time alone does not invoke Python:
an operator must continue scheduled refresh/export for expired-row cleanup.
This change does not install a new scheduler or automatically call a live DB.
Phase 2B must retain client expiry filtering and snapshot fallback/reload on lost
connections. Realtime delivery latency is separate from the ingestion cadence.

## Privileges and Realtime

Both projection and generation tables enable RLS and explicitly revoke all
inherited table privileges from PUBLIC, anon, authenticated and service_role.
Only the projection restores SELECT to anon/authenticated, with a SELECT-only
policy. Service role receives SELECT/INSERT/UPDATE/DELETE on the projection and
SELECT/UPDATE on the private singleton state. Neither browser role can write.
The RPC is SECURITY INVOKER with a fixed search path; only service_role receives
EXECUTE after PUBLIC/anon/authenticated privileges are revoked. No canonical
table receives any new grant or policy.

Only `ggongbab_public_events` is added to `supabase_realtime`, with a catalog guard
for repeat application. Default replica identity provides the safe event primary
key on DELETE; a future subscriber removes that key. Do not request private-table
subscriptions or rely on DELETE filters. Initial SELECT and reconnect reconciliation
remain necessary; a stream is not a durable snapshot. See the official
[Supabase Postgres Changes guide](https://supabase.com/docs/guides/realtime/postgres-changes).

## Portal boundary and verification

The LIST poller has no dependency on public feed synchronization. Local
`.local/portal-list-state.json` and Stage A pending are never read/uploaded here.
Title matching cannot create a canonical event. The pinned LIST query remains
the only allowed poller request; detail endpoints remain blocked. A separate
small diagnostic change logs only allowlisted reason codes, including a typed CDP
attach timeout. It does not retry credentials, relax owner checks or expose values.

`tests/ggongbab/test_public_feed.py` covers policy parity, allowlists, URL/PII
sanitization, revision/idempotency, stale removal, failures/concurrency, repository
paging, snapshot/card compatibility and SQL privileges/publication structure.
Existing Portal safety tests also run. All tests use mocks/fakes/static SQL;
no migration execution, live SQL privilege test or realtime delivery test has been
performed. Those require the operator's later manual migration/acceptance stage.
