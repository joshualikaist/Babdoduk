-- 내 꽁밥 캘린더 구독 (owner 2026-11-12, "1번부터 가도 돼 허락!"; docs/CALENDAR_FEED.md).
-- REVIEW AND APPLY MANUALLY in the Supabase SQL editor, after 011. Application code never runs it.
--
-- A signed-in visitor subscribes their phone's calendar (iPhone: one tap, then 구독) to a private address
-- that lists the free-food events they starred. The address holds a long random token: whoever has it
-- reads that one list (titles and times the visitor saved, never a name, email or account id), so it is
-- treated like a password-less share link and can be replaced at any time, which stops the old address.
--
-- Two functions and one table. The signed-in owner makes or replaces their token; the calendar server
-- (api/cal.js, anon) reads a list by token. The table itself is closed to anon and authenticated.
begin;

create extension if not exists pgcrypto with schema extensions;

create table if not exists public.calendar_feeds (
  user_id uuid primary key references auth.users (id) on delete cascade,
  token text not null unique check (token ~ '^[A-Za-z0-9_-]{43}$'),
  created_at timestamptz not null default now(),
  read_at timestamptz
);
alter table public.calendar_feeds enable row level security;
revoke all on table public.calendar_feeds from public, anon, authenticated;

-- The signed-in user's token, made on first use; p_new replaces it (the old address stops working).
create or replace function public.my_calendar_feed(p_new boolean default false)
returns text
language plpgsql
security definer
set search_path = ''
as $$
declare
  me uuid := auth.uid();
  t text;
begin
  if me is null then raise exception 'sign in first' using errcode = '28000'; end if;
  if not p_new then
    select token into t from public.calendar_feeds where user_id = me;
    if t is not null then return t; end if;
  end if;
  -- 32 random bytes, base64url without padding: 43 characters.
  t := translate(rtrim(encode(extensions.gen_random_bytes(32), 'base64'), '='), '+/', '-_');
  insert into public.calendar_feeds (user_id, token) values (me, t)
  on conflict (user_id) do update set token = excluded.token, created_at = now(), read_at = null;
  return t;
end;
$$;

-- The calendar server's read: the starred events of the token's owner, newest 300 at most, as id,
-- saved time and the saved snapshot (title, startAt, endAt, place). Nothing for an unknown token.
create or replace function public.calendar_feed_events(p_token text)
returns table (event_id text, saved_at timestamptz, seen jsonb)
language plpgsql
security definer
set search_path = ''
as $$
declare
  owner uuid;
begin
  if p_token is null or p_token !~ '^[A-Za-z0-9_-]{43}$' then return; end if;
  update public.calendar_feeds f set read_at = now() where f.token = p_token returning f.user_id into owner;
  if owner is null then return; end if;
  return query
    select s.event_id, s.saved_at, s.seen
      from public.saved_events s
     where s.user_id = owner
     order by s.saved_at desc
     limit 300;
end;
$$;

revoke all on function public.my_calendar_feed(boolean), public.calendar_feed_events(text) from public, anon, authenticated;
grant execute on function public.my_calendar_feed(boolean) to authenticated;
grant execute on function public.calendar_feed_events(text) to anon, authenticated;

commit;
