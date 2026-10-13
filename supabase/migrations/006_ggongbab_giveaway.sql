-- 2026-10-14. REVIEW AND APPLY MANUALLY after 004 (and 005); not applied by application code.
-- Owner decision 2026-10-14: list events with a prize draw or giveaway (marked 🎁, apart from the
-- free-food counts) and publish food evidence read only from a poster, recording that source.
--
-- Apply this BEFORE the code that writes these columns reaches main: until then the refresh's
-- event writes and public-feed sync use the old shape, which this migration keeps accepting.
begin;

-- Canonical events: new nullable/defaulted columns only; existing rows and writers are unaffected.
alter table public.events
  add column if not exists giveaway text not null default 'unknown',
  add column if not exists giveaway_description text,
  add column if not exists food_evidence_source text;
alter table public.events drop constraint if exists events_giveaway_check;
alter table public.events add constraint events_giveaway_check
  check (giveaway in ('true', 'false', 'unknown'));
alter table public.events drop constraint if exists events_food_evidence_source_check;
alter table public.events add constraint events_food_evidence_source_check
  check (food_evidence_source is null or food_evidence_source in ('text', 'poster'));

-- Public projection: a row is explicit free food OR a giveaway listing.
alter table public.ggongbab_public_events
  add column if not exists food_source text not null default '',
  add column if not exists giveaway text not null default 'false',
  add column if not exists giveaway_description text not null default '';
alter table public.ggongbab_public_events drop constraint if exists ggongbab_public_events_food_source_check;
alter table public.ggongbab_public_events add constraint ggongbab_public_events_food_source_check
  check (food_source in ('', 'text', 'poster'));
alter table public.ggongbab_public_events drop constraint if exists ggongbab_public_events_giveaway_check;
alter table public.ggongbab_public_events add constraint ggongbab_public_events_giveaway_check
  check (giveaway in ('true', 'false'));
-- 004 required food_provided = 'true' with an inline (auto-named) check; replace it.
alter table public.ggongbab_public_events drop constraint if exists ggongbab_public_events_food_provided_check;
alter table public.ggongbab_public_events add constraint ggongbab_public_events_food_provided_check
  check (food_provided in ('true', 'false', 'unknown') and (food_provided = 'true' or giveaway = 'true'));

-- The RPC accepts the 004 key set (old code) and the 004 set plus the three new keys (new code).
create or replace function public.ggongbab_replace_public_feed(p_generation bigint, p_rows jsonb)
returns bigint language plpgsql security invoker set search_path = pg_catalog, public
as $$
declare
  current_generation bigint;
  required_keys constant text[] := array[
    'id', 'title', 'summary', 'start_at', 'end_at', 'date_text', 'time_text',
    'location_name', 'building', 'room', 'food_provided', 'food_type', 'food_description',
    'organizer', 'eligibility', 'registration_required', 'registration_deadline',
    'registration_url', 'source_types', 'confidence', 'content_revision'];
  optional_keys constant text[] := array['food_source', 'giveaway', 'giveaway_description'];
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
    if not (item ?& required_keys) or exists (
      select 1 from jsonb_object_keys(item) as keys(key)
      where not (key = any(required_keys) or key = any(optional_keys))
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
    registration_deadline, registration_url, source_types, confidence, content_revision,
    food_source, giveaway, giveaway_description, updated_at
  ) select
    id, title, summary, start_at, end_at, date_text, time_text, location_name, building, room,
    food_provided, food_type, food_description, organizer, eligibility, registration_required,
    registration_deadline, registration_url, source_types, confidence, content_revision,
    coalesce(food_source, ''), coalesce(giveaway, 'false'), coalesce(giveaway_description, ''), now()
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
    content_revision = excluded.content_revision,
    food_source = excluded.food_source, giveaway = excluded.giveaway,
    giveaway_description = excluded.giveaway_description, updated_at = now()
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
commit;

-- Check after applying (should list the three new columns of each table, and one row):
--   select table_name, column_name from information_schema.columns
--    where table_schema = 'public' and column_name in
--      ('giveaway', 'giveaway_description', 'food_evidence_source', 'food_source') order by 1, 2;
--   select pg_get_constraintdef(oid) from pg_constraint
--    where conname = 'ggongbab_public_events_food_provided_check';
