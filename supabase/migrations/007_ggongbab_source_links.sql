-- 2026-10-31. REVIEW AND APPLY MANUALLY after 006; not applied by application code.
-- Owner decision 2026-10-31: an event handed over by the Instagram radar is published as source
-- `instagram` with a link to the post, and one from the reader tip board as source `tip` (no link)
-- (scripts/ggongbab/source_origin.py). The projection also carries the public links the snapshot's
-- sources already hold (KAIST notices, Babdoduk's own entries, Instagram posts) in `source_links`.
--
-- Either order is safe. Before this migration the public-feed sync finds no `source_links` column
-- (public_feed_has_links) and writes the 006 shape, with those two origins as `dooray`, and the lab
-- page reads the 006 columns; after it, both use the new shape. The canonical tables are unchanged:
-- such an item is still a Dooray raw item, its origin is in raw_items.metadata.
begin;

alter table public.ggongbab_public_events drop constraint if exists ggongbab_public_events_source_types_check;
alter table public.ggongbab_public_events add constraint ggongbab_public_events_source_types_check
  check (cardinality(source_types) > 0 and source_types <@
    array['dooray', 'dooray_mailbox', 'kaist_public', 'manual', 'portal', 'instagram', 'tip']::text[]);
-- 004's inline check is auto-named; stop rather than leave an older allowlist beside this one.
do $$
begin
  if exists (select 1 from pg_constraint where conrelid = 'public.ggongbab_public_events'::regclass
             and contype = 'c' and conname <> 'ggongbab_public_events_source_types_check'
             and pg_get_constraintdef(oid) like '%source_types%') then
    raise exception 'PUBLIC_FEED_SOURCE_TYPES_CHECK_NOT_REPLACED';
  end if;
end;
$$;

-- Each link: exactly {"type", "url"}; a notice or own entry an https URL, a post its canonical permalink.
create or replace function public.ggongbab_public_source_links_ok(p_links jsonb)
returns boolean language plpgsql immutable set search_path = pg_catalog
as $$
declare
  link jsonb;
begin
  if p_links is null or jsonb_typeof(p_links) <> 'array' then
    return false;
  end if;
  if jsonb_array_length(p_links) > 8 then
    return false;
  end if;
  for link in select value from jsonb_array_elements(p_links) loop
    if jsonb_typeof(link) <> 'object' then
      return false;
    end if;
    if (select array_agg(k order by k) from jsonb_object_keys(link) as keys(k)) is distinct from array['type', 'url']
       or jsonb_typeof(link->'type') <> 'string' or jsonb_typeof(link->'url') <> 'string' then
      return false;
    end if;
    if link->>'type' = 'instagram' then
      if link->>'url' !~ '^https://www\.instagram\.com/(p|reel)/[A-Za-z0-9_-]{5,20}/$' then
        return false;
      end if;
    elsif link->>'type' in ('kaist_public', 'manual') then
      if length(link->>'url') > 2048 or link->>'url' !~ '^https://[^[:space:]<>"\\]+$' then
        return false;
      end if;
    else
      return false;
    end if;
  end loop;
  return true;
end;
$$;
revoke all on function public.ggongbab_public_source_links_ok(jsonb) from public, anon, authenticated, service_role;
grant execute on function public.ggongbab_public_source_links_ok(jsonb) to service_role;

alter table public.ggongbab_public_events
  add column if not exists source_links jsonb not null default '[]'::jsonb;
alter table public.ggongbab_public_events drop constraint if exists ggongbab_public_events_source_links_check;
alter table public.ggongbab_public_events add constraint ggongbab_public_events_source_links_check
  check (public.ggongbab_public_source_links_ok(source_links));

-- The RPC accepts the 006 key set (old code) and the 006 set plus `source_links` (new code).
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
  optional_keys constant text[] := array['food_source', 'giveaway', 'giveaway_description', 'source_links'];
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
    food_source, giveaway, giveaway_description, source_links, updated_at
  ) select
    id, title, summary, start_at, end_at, date_text, time_text, location_name, building, room,
    food_provided, food_type, food_description, organizer, eligibility, registration_required,
    registration_deadline, registration_url, source_types, confidence, content_revision,
    coalesce(food_source, ''), coalesce(giveaway, 'false'), coalesce(giveaway_description, ''),
    coalesce(source_links, '[]'::jsonb), now()
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
    giveaway_description = excluded.giveaway_description, source_links = excluded.source_links,
    updated_at = now()
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

-- Check after applying (should list source_links, and a constraint naming instagram and tip):
--   select column_name, data_type from information_schema.columns
--    where table_schema = 'public' and table_name = 'ggongbab_public_events' and column_name = 'source_links';
--   select pg_get_constraintdef(oid) from pg_constraint
--    where conname = 'ggongbab_public_events_source_types_check';
