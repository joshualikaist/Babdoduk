-- 내 꽁밥 캘린더: 남은 예전 구독 알리기 (owner 2026-11-19, "하나만 되도록 하는건 잘 된거 같아. 그래도 문제는 구독은
-- 쌓여"; docs/CALENDAR_FEED.md). REVIEW AND APPLY MANUALLY in the Supabase SQL editor, after 016. Application
-- code never runs it. It is idempotent.
--
-- 016 makes the newest connection the only one that lists the events, but a website cannot delete a
-- subscription from a phone: the old one stays in the Calendar app, empty. So the old addresses are kept:
--
--   * calendar_feed_events() remembers the address a new connection replaces (calendar_feed_retired), and a
--     read of such an address answers one marker row (event_id 'babdoduk:retired'). api/cal.js turns it into
--     a single notice in that calendar, "지난 구독 · 지워 주세요"; an older api/cal.js skips the row as an
--     unknown event, so it keeps answering an empty calendar as before.
--   * my_calendar_link() also says when an old address was last read (leftover_at), so 마이 밥도둑 can tell
--     the visitor that an old subscription is still on a phone and how to delete it.
--
-- The kept addresses list nothing and go with the account.
begin;

create table if not exists public.calendar_feed_retired (
  token text primary key check (token ~ '^[A-Za-z0-9_-]{43}$'),
  user_id uuid not null references auth.users (id) on delete cascade,
  retired_at timestamptz not null default now(),
  read_at timestamptz
);
create index if not exists calendar_feed_retired_user_idx on public.calendar_feed_retired (user_id);
alter table public.calendar_feed_retired enable row level security;
revoke all on table public.calendar_feed_retired from public, anon, authenticated;

-- As in 016, plus leftover_at: the last read of any of this account's old addresses.
create or replace function public.my_calendar_link()
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  me uuid := auth.uid();
  r public.calendar_feeds%rowtype;
  leftover timestamptz;
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
  select max(x.read_at) into leftover from public.calendar_feed_retired x where x.user_id = me;
  return jsonb_build_object('link', r.next_token, 'read_at', r.read_at, 'linked_at', r.linked_at,
                            'leftover_at', leftover);
end;
$$;

-- As in 016, except that the replaced address is kept, and reading a kept address answers the marker row.
create or replace function public.calendar_feed_events(p_token text)
returns table (event_id text, saved_at timestamptz, seen jsonb)
language plpgsql
security definer
set search_path = ''
as $$
declare
  owner uuid;
  old text;
  gone timestamptz;
begin
  if p_token is null or p_token !~ '^[A-Za-z0-9_-]{43}$' then return; end if;
  select f.user_id, f.token into owner, old from public.calendar_feeds f where f.next_token = p_token for update;
  if owner is not null then
    insert into public.calendar_feed_retired (token, user_id) values (old, owner) on conflict (token) do nothing;
    update public.calendar_feeds f
       set token = f.next_token, next_token = null, read_at = now(), linked_at = now()
     where f.user_id = owner;
  else
    update public.calendar_feeds f set read_at = now() where f.token = p_token returning f.user_id into owner;
  end if;
  if owner is null then
    update public.calendar_feed_retired x set read_at = now() where x.token = p_token returning x.retired_at into gone;
    if gone is not null then
      return query select 'babdoduk:retired'::text, gone, null::jsonb;
    end if;
    return;
  end if;
  return query
    select s.event_id, s.saved_at, s.seen
      from public.saved_events s
     where s.user_id = owner
     order by s.saved_at desc
     limit 300;
end;
$$;

revoke all on function public.my_calendar_link(), public.calendar_feed_events(text) from public, anon, authenticated;
grant execute on function public.my_calendar_link() to authenticated;
grant execute on function public.calendar_feed_events(text) to anon, authenticated;

commit;
