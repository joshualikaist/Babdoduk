-- 오늘 뭐 먹지: everyone's taste (owner 2026-11-05, "방법 A가 맞는 것 같아"), as anonymous counts per dish.
-- REVIEW AND APPLY MANUALLY in the Supabase SQL editor (after 009); application code never runs it.
-- Then seed the pool: python scripts/pick_stats.py seed (backend key, docs/PICK_STATS.md).
--
-- Stored: per dish only how often the machine drew it, how often a person pressed 👍 이거 먹을래요 on it
-- and how often a person drew again past it without that. No row per person or per draw, no identity,
-- no free text. A browser can read the counts and add one signal through pick_record, which checks
-- the signal, the dish (a row of pick_dish_stats) and a rate limit; it cannot write a table directly.
begin;

create extension if not exists pgcrypto with schema extensions;

create table if not exists public.pick_dish_stats (
  dish_id text primary key check (dish_id ~ '^[a-z0-9]+(-[a-z0-9]+)*$' and length(dish_id) <= 64),
  draws bigint not null default 0 check (draws >= 0),
  likes bigint not null default 0 check (likes >= 0),
  rerolls bigint not null default 0 check (rerolls >= 0),
  updated_at timestamptz not null default now()
);
alter table public.pick_dish_stats enable row level security;
revoke all on table public.pick_dish_stats from public, anon, authenticated;
grant select on table public.pick_dish_stats to anon, authenticated;
grant select, insert, update, delete on table public.pick_dish_stats to service_role;
drop policy if exists pick_stats_read on public.pick_dish_stats;
create policy pick_stats_read on public.pick_dish_stats for select to anon, authenticated using (true);

-- Abuse limit: at most 120 signals per client per hour. The client is a salted hash of the forwarded
-- address and the day (the salt never leaves the database); rows go after a day.
create table if not exists public.pick_secret (
  singleton boolean primary key default true check (singleton),
  salt text not null default encode(extensions.gen_random_bytes(32), 'hex')
);
insert into public.pick_secret(singleton) values (true) on conflict do nothing;
alter table public.pick_secret enable row level security;
revoke all on table public.pick_secret from public, anon, authenticated, service_role;

create table if not exists public.pick_rate (
  client_hash text not null,
  window_start timestamptz not null,
  signals integer not null default 0,
  primary key (client_hash, window_start)
);
alter table public.pick_rate enable row level security;
revoke all on table public.pick_rate from public, anon, authenticated, service_role;

-- One signal for one dish: 'draw' (the machine drew it), 'like' (👍 이거 먹을래요) or 'reroll' (다시 뽑기
-- past it without a 👍). SECURITY DEFINER so the browser roles reach the counts only through it.
create or replace function public.pick_record(p_dish text, p_signal text)
returns void language plpgsql security definer set search_path = pg_catalog, public
as $$
declare
  forwarded text;
  client text;
  recorded integer;
begin
  if p_signal is null or p_signal not in ('draw', 'like', 'reroll') then
    raise exception 'PICK_INVALID_SIGNAL';
  end if;
  if p_dish is null or not exists (select 1 from public.pick_dish_stats where dish_id = p_dish) then
    raise exception 'PICK_UNKNOWN_DISH';
  end if;

  forwarded := btrim(split_part(coalesce(current_setting('request.headers', true)::json ->> 'x-forwarded-for', ''), ',', 1));
  client := encode(extensions.digest((select salt from public.pick_secret) || current_date::text || forwarded, 'sha256'), 'hex');
  insert into public.pick_rate as r (client_hash, window_start, signals)
    values (client, date_trunc('hour', now()), 1)
    on conflict (client_hash, window_start) do update set signals = r.signals + 1
    returning signals into recorded;
  delete from public.pick_rate where window_start < now() - interval '1 day';
  if recorded > 120 then
    raise exception 'PICK_RATE_LIMITED';
  end if;

  update public.pick_dish_stats set
    draws = draws + (p_signal = 'draw')::int,
    likes = likes + (p_signal = 'like')::int,
    rerolls = rerolls + (p_signal = 'reroll')::int,
    updated_at = now()
  where dish_id = p_dish;
end;
$$;
revoke all on function public.pick_record(text, text) from public;
grant execute on function public.pick_record(text, text) to anon, authenticated, service_role;
commit;
