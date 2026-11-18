-- 내 꽁밥 캘린더: 마지막 연결 하나만 (owner 2026-11-19, "동일한 행사가 두개 뜨는거지 ... 로직을 전면 수정해";
-- docs/CALENDAR_FEED.md). REVIEW AND APPLY MANUALLY in the Supabase SQL editor, after 013. Application code
-- never runs it. It is idempotent.
--
-- The problem: an iPhone keeps every subscription it is given. A visitor who taps 연결 a second time (for
-- example because a new star has not shown up yet) gets a second calendar with the same list, so every
-- event shows twice. The phone cannot be asked to replace a subscription, so the address must change:
--
--   * my_calendar_link() hands out a fresh address (next_token) next to the live one (token), plus when a
--     calendar last read the list (read_at) and when the current connection was made (linked_at), so the
--     card on 마이 밥도둑 can say "연결됨" and stop offering the button as if nothing were connected.
--   * the first time a calendar reads the fresh address, calendar_feed_events() makes it the only live
--     address: the old one (and every subscription still using it) answers an empty list from then on.
--
-- Whatever the visitor taps, exactly one subscription shows the events. my_calendar_feed() (013) keeps
-- working for an older page: it returns the live address.
begin;

alter table public.calendar_feeds add column if not exists next_token text;
alter table public.calendar_feeds add column if not exists linked_at timestamptz;
do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'calendar_feeds_next_token_key') then
    alter table public.calendar_feeds add constraint calendar_feeds_next_token_key unique (next_token);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'calendar_feeds_next_token_check') then
    alter table public.calendar_feeds add constraint calendar_feeds_next_token_check
      check (next_token is null or next_token ~ '^[A-Za-z0-9_-]{43}$');
  end if;
end;
$$;

-- 32 random bytes, base64url without padding: 43 characters (the same shape as 013's tokens).
create or replace function public.calendar_new_token()
returns text
language sql
volatile
set search_path = ''
as $$
  select translate(rtrim(encode(extensions.gen_random_bytes(32), 'base64'), '='), '+/', '-_');
$$;

-- The signed-in user's connection: the address to subscribe to now, and the state of the current one.
-- The address stays the same until a calendar reads it, so a page opened twice shows one address.
create or replace function public.my_calendar_link()
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  me uuid := auth.uid();
  r public.calendar_feeds%rowtype;
begin
  if me is null then raise exception 'sign in first' using errcode = '28000'; end if;
  select * into r from public.calendar_feeds where user_id = me for update;
  if not found then
    insert into public.calendar_feeds (user_id, token, next_token)
    values (me, public.calendar_new_token(), public.calendar_new_token())
    returning * into r;
  elsif r.next_token is null then
    update public.calendar_feeds set next_token = public.calendar_new_token() where user_id = me
    returning * into r;
  end if;
  return jsonb_build_object('link', r.next_token, 'read_at', r.read_at, 'linked_at', r.linked_at);
end;
$$;

-- The calendar server's read (api/cal.js, anon), as in 013, except that the first read of a fresh address
-- makes it the live one: the old address stops, so an older subscription of the same list goes empty.
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
  update public.calendar_feeds f
     set token = f.next_token, next_token = null, read_at = now(), linked_at = now()
   where f.next_token = p_token
  returning f.user_id into owner;
  if owner is null then
    update public.calendar_feeds f set read_at = now() where f.token = p_token returning f.user_id into owner;
  end if;
  if owner is null then return; end if;
  return query
    select s.event_id, s.saved_at, s.seen
      from public.saved_events s
     where s.user_id = owner
     order by s.saved_at desc
     limit 300;
end;
$$;

revoke all on function public.calendar_new_token() from public, anon, authenticated;
revoke all on function public.my_calendar_link(), public.calendar_feed_events(text) from public, anon, authenticated;
grant execute on function public.my_calendar_link() to authenticated;
grant execute on function public.calendar_feed_events(text) to anon, authenticated;

commit;
