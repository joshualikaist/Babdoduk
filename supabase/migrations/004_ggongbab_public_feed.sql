-- Phase 2A. REVIEW AND APPLY MANUALLY after 003; not applied by application code.
begin;

-- No foreign keys: browser roles cannot traverse canonical/private relationships.
create table if not exists public.ggongbab_public_events (
  id uuid primary key,
  title text not null check (length(btrim(title)) > 0),
  summary text not null,
  start_at timestamptz not null,
  end_at timestamptz check (end_at >= start_at),
  date_text text not null,
  time_text text not null,
  location_name text not null,
  building text not null,
  room text not null,
  food_provided text not null check (food_provided = 'true'),
  food_type text not null check (food_type in
    ('meal', 'lunchbox', 'snack', 'refreshment', 'beverage', 'coupon', 'other', 'unknown')),
  food_description text not null,
  organizer text not null,
  eligibility text not null,
  registration_required text not null check (registration_required in ('true', 'false', 'unknown')),
  registration_deadline timestamptz,
  registration_url text not null,
  source_types text[] not null check (cardinality(source_types) > 0 and
    source_types <@ array['dooray', 'dooray_mailbox', 'kaist_public', 'manual', 'portal']::text[]),
  confidence double precision not null check (confidence >= 0 and confidence <= 1),
  content_revision text not null check (content_revision ~ '^[0-9a-f]{64}$'),
  updated_at timestamptz not null default now()
);
create index if not exists ggongbab_public_events_start_idx on public.ggongbab_public_events(start_at, id);
alter table public.ggongbab_public_events enable row level security;
revoke all on table public.ggongbab_public_events from public, anon, authenticated, service_role;
grant select on table public.ggongbab_public_events to anon, authenticated;
grant select, insert, update, delete on table public.ggongbab_public_events to service_role;
drop policy if exists ggongbab_public_read on public.ggongbab_public_events;
create policy ggongbab_public_read on public.ggongbab_public_events
  for select to anon, authenticated using (true);

-- Backend-only compare-and-swap generation; never in Realtime or browser output.
create table if not exists public.ggongbab_public_feed_state (
  singleton boolean primary key default true check (singleton),
  generation bigint not null default 0 check (generation >= 0)
);
insert into public.ggongbab_public_feed_state(singleton) values (true) on conflict do nothing;
alter table public.ggongbab_public_feed_state enable row level security;
revoke all on table public.ggongbab_public_feed_state from public, anon, authenticated, service_role;
grant select, update on table public.ggongbab_public_feed_state to service_role;

-- One RPC transaction: lock -> reject stale preparation -> validate -> upsert -> delete.
-- Exceptions roll back every projection change, without touching canonical events.
-- SECURITY INVOKER: no privilege escalation; only service_role can call this RPC.
create or replace function public.ggongbab_replace_public_feed(p_generation bigint, p_rows jsonb)
returns bigint language plpgsql security invoker set search_path = pg_catalog, public
as $$
declare
  current_generation bigint;
  allowed_keys constant text[] := array[
    'id', 'title', 'summary', 'start_at', 'end_at', 'date_text', 'time_text',
    'location_name', 'building', 'room', 'food_provided', 'food_type', 'food_description',
    'organizer', 'eligibility', 'registration_required', 'registration_deadline',
    'registration_url', 'source_types', 'confidence', 'content_revision'];
  item jsonb;
begin
  select generation into current_generation from public.ggongbab_public_feed_state
    where singleton = true for update;
  if current_generation is null or p_generation is distinct from current_generation then
    raise exception 'PUBLIC_FEED_CONCURRENT_SYNC';
  end if;
  if p_rows is null or jsonb_typeof(p_rows) <> 'array' then
    raise exception 'PUBLIC_FEED_INVALID_ROWS';
  end if;
  for item in select value from jsonb_array_elements(p_rows) loop
    if jsonb_typeof(item) <> 'object' then
      raise exception 'PUBLIC_FEED_INVALID_ROW';
    end if;
    if not (item ?& allowed_keys) or exists (
      select 1 from jsonb_object_keys(item) as keys(key) where not (key = any(allowed_keys))
    ) then
      raise exception 'PUBLIC_FEED_INVALID_FIELDS';
    end if;
  end loop;
  if (select count(*) <> count(distinct value->>'id') from jsonb_array_elements(p_rows)) then
    raise exception 'PUBLIC_FEED_DUPLICATE_ID';
  end if;

  insert into public.ggongbab_public_events as existing (
    id, title, summary, start_at, end_at, date_text, time_text, location_name, building, room,
    food_provided, food_type, food_description, organizer, eligibility, registration_required,
    registration_deadline, registration_url, source_types, confidence, content_revision, updated_at
  ) select
    id, title, summary, start_at, end_at, date_text, time_text, location_name, building, room,
    food_provided, food_type, food_description, organizer, eligibility, registration_required,
    registration_deadline, registration_url, source_types, confidence, content_revision, now()
  from jsonb_populate_recordset(null::public.ggongbab_public_events, p_rows)
  on conflict (id) do update set
    title = excluded.title, summary = excluded.summary,
    start_at = excluded.start_at, end_at = excluded.end_at,
    date_text = excluded.date_text, time_text = excluded.time_text,
    location_name = excluded.location_name, building = excluded.building, room = excluded.room,
    food_provided = excluded.food_provided, food_type = excluded.food_type,
    food_description = excluded.food_description, organizer = excluded.organizer,
    eligibility = excluded.eligibility, registration_required = excluded.registration_required,
    registration_deadline = excluded.registration_deadline, registration_url = excluded.registration_url,
    source_types = excluded.source_types, confidence = excluded.confidence,
    content_revision = excluded.content_revision, updated_at = now()
  where existing.content_revision is distinct from excluded.content_revision;

  delete from public.ggongbab_public_events as existing
    where not exists (select 1 from jsonb_array_elements(p_rows) desired
                      where (desired->>'id')::uuid = existing.id);
  update public.ggongbab_public_feed_state set generation = generation + 1 where singleton = true;
  return current_generation + 1;
end;
$$;
revoke all on function public.ggongbab_replace_public_feed(bigint, jsonb) from public, anon, authenticated, service_role;
grant execute on function public.ggongbab_replace_public_feed(bigint, jsonb) to service_role;

-- Default replica identity exposes only the safe primary key for DELETE.
alter table public.ggongbab_public_events replica identity default;
do $$
begin
  if not exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    raise exception 'PUBLIC_FEED_REALTIME_PUBLICATION_MISSING';
  end if;
  -- Never silently accept an existing broad publication of private tables.
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime' and puballtables)
     or exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime'
                and schemaname = 'public' and tablename in
                ('raw_items', 'attachments', 'ai_parse_runs', 'events', 'event_sources',
                 'sources', 'event_conflicts', 'agent_heartbeats', 'ingest_runs', 'ggongbab_public_feed_state')) then
    raise exception 'PUBLIC_FEED_PRIVATE_REALTIME_PUBLICATION_REQUIRES_REVIEW';
  end if;
  if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime'
                  and schemaname = 'public' and tablename = 'ggongbab_public_events') then
    alter publication supabase_realtime add table public.ggongbab_public_events;
  end if;
end;
$$;
commit;
