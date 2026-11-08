-- 마이 밥도둑 accounts (밥도둑 2.0 Phase 2, owner approved the phase 2026-11-08). docs/MY_BABDODUK.md.
-- REVIEW AND APPLY MANUALLY in the Supabase SQL editor, after 010 and after Google and Kakao are enabled
-- under Authentication. Application code never runs it.
--
-- Login is optional. A signed-in visitor keeps their saved free-food events and their restaurant list
-- (먹킷리스트) on the server so they follow them across devices. Everything here is private to its owner:
-- every table denies by default, a signed-in user reads and writes only rows whose user_id is their
-- own auth.uid(), and anon reads nothing. The one public path is public_place_list(slug): a list its
-- owner made public, as a title and restaurant ids only (never the owner, a name, a memo or a status).
-- Deleting the account removes every row here through ON DELETE CASCADE from auth.users.
begin;

create extension if not exists pgcrypto with schema extensions;

-- ---------------------------------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------------------------------

-- A private profile: only the name the user chose to show themselves. Never public.
create table if not exists public.profiles (
  user_id uuid primary key references auth.users (id) on delete cascade,
  display_name text check (display_name is null or char_length(btrim(display_name)) between 1 and 40),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Saved free-food events: the browser store babdoduk-ggongbab-saved v1, one row per item
-- (js/ggongbab-live.js). event_id is the public feed id, or <id>#<n> for one day of a multi-day event.
create table if not exists public.saved_events (
  user_id uuid not null references auth.users (id) on delete cascade,
  event_id text not null check (event_id ~ '^[A-Za-z0-9_-]{1,80}(#[0-9]{1,2})?$'),
  saved_at timestamptz not null default now(),
  seen jsonb not null default '{}'::jsonb
    check (jsonb_typeof(seen) = 'object' and pg_column_size(seen) <= 2048),
  primary key (user_id, event_id)
);

-- 먹킷리스트: want / been / again with a private memo (Phase 3, babdoduk-places-saved v1).
create table if not exists public.saved_places (
  user_id uuid not null references auth.users (id) on delete cascade,
  place_id text not null check (place_id ~ '^[A-Za-z0-9_-]{1,80}$'),
  status text not null check (status in ('want', 'been', 'again')),
  memo text not null default '' check (char_length(memo) <= 500),
  saved_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, place_id)
);

-- A restaurant list the owner may share by link. Private until is_public, and then only through
-- public_place_list(share_slug). Turning sharing off clears the slug, so an old link stops working.
create table if not exists public.place_lists (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  title text not null check (char_length(btrim(title)) between 1 and 40),
  is_public boolean not null default false,
  share_slug text unique check (share_slug is null or share_slug ~ '^[A-Za-z0-9_-]{22}$'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (is_public = (share_slug is not null))
);
create index if not exists place_lists_user on public.place_lists (user_id);

create table if not exists public.place_list_items (
  list_id uuid not null references public.place_lists (id) on delete cascade,
  place_id text not null check (place_id ~ '^[A-Za-z0-9_-]{1,80}$'),
  added_at timestamptz not null default now(),
  primary key (list_id, place_id)
);

-- ---------------------------------------------------------------------------------------------------
-- Limits (one person's data stays small; a runaway client cannot fill the database)
-- ---------------------------------------------------------------------------------------------------
create or replace function public.accounts_enforce_limits()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  n integer;
begin
  if tg_table_name = 'saved_events' then
    select count(*) into n from public.saved_events where user_id = new.user_id;
    if n >= 300 then raise exception 'saved_events limit' using errcode = 'P0001'; end if;
  elsif tg_table_name = 'saved_places' then
    select count(*) into n from public.saved_places where user_id = new.user_id;
    if n >= 1000 then raise exception 'saved_places limit' using errcode = 'P0001'; end if;
  elsif tg_table_name = 'place_lists' then
    select count(*) into n from public.place_lists where user_id = new.user_id;
    if n >= 20 then raise exception 'place_lists limit' using errcode = 'P0001'; end if;
  elsif tg_table_name = 'place_list_items' then
    select count(*) into n from public.place_list_items where list_id = new.list_id;
    if n >= 200 then raise exception 'place_list_items limit' using errcode = 'P0001'; end if;
  end if;
  return new;
end;
$$;

drop trigger if exists saved_events_limit on public.saved_events;
create trigger saved_events_limit before insert on public.saved_events
  for each row execute function public.accounts_enforce_limits();
drop trigger if exists saved_places_limit on public.saved_places;
create trigger saved_places_limit before insert on public.saved_places
  for each row execute function public.accounts_enforce_limits();
drop trigger if exists place_lists_limit on public.place_lists;
create trigger place_lists_limit before insert on public.place_lists
  for each row execute function public.accounts_enforce_limits();
drop trigger if exists place_list_items_limit on public.place_list_items;
create trigger place_list_items_limit before insert on public.place_list_items
  for each row execute function public.accounts_enforce_limits();

-- updated_at follows every change; user_id never moves to another user.
create or replace function public.accounts_touch()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.user_id is distinct from old.user_id then
    raise exception 'user_id is fixed' using errcode = 'P0001';
  end if;
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists profiles_touch on public.profiles;
create trigger profiles_touch before update on public.profiles
  for each row execute function public.accounts_touch();
drop trigger if exists saved_places_touch on public.saved_places;
create trigger saved_places_touch before update on public.saved_places
  for each row execute function public.accounts_touch();
drop trigger if exists place_lists_touch on public.place_lists;
create trigger place_lists_touch before update on public.place_lists
  for each row execute function public.accounts_touch();

-- saved_events has no updated_at; its owner still never changes.
create or replace function public.accounts_fixed_owner()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.user_id is distinct from old.user_id then
    raise exception 'user_id is fixed' using errcode = 'P0001';
  end if;
  return new;
end;
$$;
drop trigger if exists saved_events_fixed_owner on public.saved_events;
create trigger saved_events_fixed_owner before update on public.saved_events
  for each row execute function public.accounts_fixed_owner();

-- ---------------------------------------------------------------------------------------------------
-- Row level security: deny by default, own rows only
-- ---------------------------------------------------------------------------------------------------
alter table public.profiles enable row level security;
alter table public.saved_events enable row level security;
alter table public.saved_places enable row level security;
alter table public.place_lists enable row level security;
alter table public.place_list_items enable row level security;

revoke all on table public.profiles, public.saved_events, public.saved_places,
  public.place_lists, public.place_list_items from public, anon, authenticated;
grant select, insert, update, delete on table public.profiles, public.saved_events,
  public.saved_places, public.place_lists, public.place_list_items to authenticated;

drop policy if exists profiles_own on public.profiles;
create policy profiles_own on public.profiles for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

drop policy if exists saved_events_own on public.saved_events;
create policy saved_events_own on public.saved_events for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

drop policy if exists saved_places_own on public.saved_places;
create policy saved_places_own on public.saved_places for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

drop policy if exists place_lists_own on public.place_lists;
create policy place_lists_own on public.place_lists for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

drop policy if exists place_list_items_own on public.place_list_items;
create policy place_list_items_own on public.place_list_items for all to authenticated
  using (exists (select 1 from public.place_lists l where l.id = list_id and l.user_id = (select auth.uid())))
  with check (exists (select 1 from public.place_lists l where l.id = list_id and l.user_id = (select auth.uid())));

-- ---------------------------------------------------------------------------------------------------
-- Functions the browser calls
-- ---------------------------------------------------------------------------------------------------

-- Guest merge (Q13): add the browser's saved events that the account lacks. An event the account
-- already has keeps the account's copy (its seen values); only the earlier saved_at wins. Never deletes.
-- Runs as the caller, so the policies above still apply. Returns how many rows were added.
create or replace function public.merge_saved_events(p_items jsonb)
returns integer
language plpgsql
security invoker
set search_path = ''
as $$
declare
  me uuid := auth.uid();
  added integer := 0;
  item jsonb;
  inserted boolean;
begin
  if me is null then raise exception 'sign in first' using errcode = '28000'; end if;
  if jsonb_typeof(p_items) is distinct from 'array' or jsonb_array_length(p_items) > 300 then
    raise exception 'bad items' using errcode = '22023';
  end if;
  for item in select value from jsonb_array_elements(p_items) loop
    if jsonb_typeof(item) is distinct from 'object'
       or coalesce(item->>'id', '') !~ '^[A-Za-z0-9_-]{1,80}(#[0-9]{1,2})?$' then
      continue;
    end if;
    insert into public.saved_events as s (user_id, event_id, saved_at, seen)
    values (
      me,
      item->>'id',
      coalesce(
        case when coalesce(item->>'savedAt', '') ~ '^\d{4}-\d{2}-\d{2}T' then (item->>'savedAt')::timestamptz end,
        now()),
      case when jsonb_typeof(item->'seen') = 'object' and pg_column_size(item->'seen') <= 2048
           then item->'seen' else '{}'::jsonb end)
    on conflict (user_id, event_id) do update
      set saved_at = least(s.saved_at, excluded.saved_at)
    returning (xmax = 0) into inserted;
    if inserted then added := added + 1; end if;
  end loop;
  return added;
end;
$$;

-- Guest merge for the restaurant list: add places the account lacks. A place it already has keeps the
-- account's status and memo; when the browser memo differs and is not empty the place id comes back in
-- "conflicts" so the page can say so (the browser copy stays in the browser, nothing is overwritten).
create or replace function public.merge_saved_places(p_items jsonb)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  me uuid := auth.uid();
  added integer := 0;
  conflicts jsonb := '[]'::jsonb;
  item jsonb;
  existing public.saved_places;
  local_memo text;
begin
  if me is null then raise exception 'sign in first' using errcode = '28000'; end if;
  if jsonb_typeof(p_items) is distinct from 'array' or jsonb_array_length(p_items) > 1000 then
    raise exception 'bad items' using errcode = '22023';
  end if;
  for item in select value from jsonb_array_elements(p_items) loop
    if jsonb_typeof(item) is distinct from 'object'
       or coalesce(item->>'id', '') !~ '^[A-Za-z0-9_-]{1,80}$'
       or coalesce(item->>'status', '') not in ('want', 'been', 'again') then
      continue;
    end if;
    local_memo := left(coalesce(item->>'memo', ''), 500);
    select * into existing from public.saved_places where user_id = me and place_id = item->>'id';
    if found then
      if btrim(local_memo) <> '' and local_memo is distinct from existing.memo then
        conflicts := conflicts || to_jsonb(item->>'id');
      end if;
      continue;
    end if;
    insert into public.saved_places (user_id, place_id, status, memo, saved_at)
    values (
      me, item->>'id', item->>'status', local_memo,
      coalesce(
        case when coalesce(item->>'savedAt', '') ~ '^\d{4}-\d{2}-\d{2}T' then (item->>'savedAt')::timestamptz end,
        now()));
    added := added + 1;
  end loop;
  return jsonb_build_object('added', added, 'conflicts', conflicts);
end;
$$;

-- Share a list or stop sharing it. A new slug each time sharing is turned on, so a link that was
-- turned off never comes back. Only the list's owner can do either (the policy decides the update).
create or replace function public.set_place_list_sharing(p_list uuid, p_public boolean)
returns text
language plpgsql
security invoker
set search_path = ''
as $$
declare
  slug text;
begin
  if auth.uid() is null then raise exception 'sign in first' using errcode = '28000'; end if;
  if p_public then
    slug := translate(rtrim(encode(extensions.gen_random_bytes(16), 'base64'), '='), '+/', '-_');
  end if;
  update public.place_lists set is_public = coalesce(p_public, false), share_slug = slug
   where id = p_list and user_id = auth.uid();
  if not found then raise exception 'no such list' using errcode = 'P0002'; end if;
  return slug;
end;
$$;

-- The only public read: a shared list's title and restaurant ids, by its slug.
create or replace function public.public_place_list(p_slug text)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
  select jsonb_build_object(
           'title', l.title,
           'places', coalesce((select jsonb_agg(i.place_id order by i.added_at)
                                 from public.place_list_items i where i.list_id = l.id), '[]'::jsonb))
    from public.place_lists l
   where p_slug ~ '^[A-Za-z0-9_-]{22}$' and l.is_public and l.share_slug = p_slug;
$$;

-- Clear what the user saved, keep the account (Q19 "저장한 개인 데이터 삭제").
create or replace function public.delete_my_saved_data()
returns void
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if auth.uid() is null then raise exception 'sign in first' using errcode = '28000'; end if;
  delete from public.saved_events where user_id = auth.uid();
  delete from public.saved_places where user_id = auth.uid();
  delete from public.place_lists where user_id = auth.uid();
end;
$$;

-- Leave (Q19 "본인 확인 후 탈퇴"): the user must have signed in within the last 10 minutes, so a
-- forgotten open session cannot delete the account. Removing auth.users cascades to every table above
-- and to Supabase's own identities and sessions.
create or replace function public.delete_my_account()
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  me uuid := auth.uid();
  signed_in timestamptz;
begin
  if me is null then raise exception 'sign in first' using errcode = '28000'; end if;
  select last_sign_in_at into signed_in from auth.users where id = me;
  if signed_in is null or signed_in < now() - interval '10 minutes' then
    raise exception 'sign in again' using errcode = '28000';
  end if;
  delete from auth.users where id = me;
end;
$$;

revoke all on function public.merge_saved_events(jsonb), public.merge_saved_places(jsonb),
  public.set_place_list_sharing(uuid, boolean), public.public_place_list(text),
  public.delete_my_saved_data(), public.delete_my_account(),
  public.accounts_enforce_limits(), public.accounts_touch(), public.accounts_fixed_owner()
  from public, anon, authenticated;
grant execute on function public.merge_saved_events(jsonb), public.merge_saved_places(jsonb),
  public.set_place_list_sharing(uuid, boolean), public.delete_my_saved_data(),
  public.delete_my_account() to authenticated;
grant execute on function public.public_place_list(text) to anon, authenticated;

commit;
