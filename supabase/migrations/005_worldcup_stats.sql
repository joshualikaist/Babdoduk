-- 먹방 월드컵 stage 2 (owner, 2026-10-13): everyone's picks, as anonymous aggregate counts.
-- REVIEW AND APPLY MANUALLY in the Supabase SQL editor (after 004); application code never runs it.
-- Then seed the pool: python scripts/worldcup_stats.py seed (backend key, docs/WORLDCUP_STATS.md).
--
-- Stored: per dish only the number of 1:1 matches, wins, games it was drawn into and titles, and
-- the number of finished games. No row per player or per game, no identity, no free text. A
-- browser can read the counts and record one finished game through worldcup_record_game, which
-- validates the whole bracket against the pool; it cannot write a table directly.
begin;

create extension if not exists pgcrypto with schema extensions;

create table if not exists public.worldcup_dish_stats (
  dish_id text primary key check (dish_id ~ '^[a-z0-9]+(-[a-z0-9]+)*$' and length(dish_id) <= 64),
  matches bigint not null default 0 check (matches >= 0),
  wins bigint not null default 0 check (wins >= 0 and wins <= matches),
  entries bigint not null default 0 check (entries >= 0),
  titles bigint not null default 0 check (titles >= 0 and titles <= entries),
  updated_at timestamptz not null default now()
);
alter table public.worldcup_dish_stats enable row level security;
revoke all on table public.worldcup_dish_stats from public, anon, authenticated;
grant select on table public.worldcup_dish_stats to anon, authenticated;
grant select, insert, update, delete on table public.worldcup_dish_stats to service_role;
drop policy if exists worldcup_stats_read on public.worldcup_dish_stats;
create policy worldcup_stats_read on public.worldcup_dish_stats for select to anon, authenticated using (true);

create table if not exists public.worldcup_totals (
  singleton boolean primary key default true check (singleton),
  games bigint not null default 0 check (games >= 0),
  updated_at timestamptz not null default now()
);
insert into public.worldcup_totals(singleton) values (true) on conflict do nothing;
alter table public.worldcup_totals enable row level security;
revoke all on table public.worldcup_totals from public, anon, authenticated;
grant select on table public.worldcup_totals to anon, authenticated;
grant select, update on table public.worldcup_totals to service_role;
drop policy if exists worldcup_totals_read on public.worldcup_totals;
create policy worldcup_totals_read on public.worldcup_totals for select to anon, authenticated using (true);

-- Abuse limit: at most 30 recorded games per client per hour. The client is a salted hash of the
-- forwarded address and the day (the salt never leaves the database); rows go after a day.
create table if not exists public.worldcup_secret (
  singleton boolean primary key default true check (singleton),
  salt text not null default encode(extensions.gen_random_bytes(32), 'hex')
);
insert into public.worldcup_secret(singleton) values (true) on conflict do nothing;
alter table public.worldcup_secret enable row level security;
revoke all on table public.worldcup_secret from public, anon, authenticated, service_role;

create table if not exists public.worldcup_rate (
  client_hash text not null,
  window_start timestamptz not null,
  games integer not null default 0,
  primary key (client_hash, window_start)
);
alter table public.worldcup_rate enable row level security;
revoke all on table public.worldcup_rate from public, anon, authenticated, service_role;

-- One finished game: p_matches holds the size - 1 matches in play order as [winner, loser].
-- Round 1 pairs the size distinct dishes two by two; every later round pairs the previous
-- round's winners in order; every dish must be in the pool (a row of worldcup_dish_stats).
-- SECURITY DEFINER so the browser roles reach the counts only through this validation.
create or replace function public.worldcup_record_game(p_size integer, p_matches jsonb)
returns void language plpgsql security definer set search_path = pg_catalog, public
as $$
declare
  round_size integer := p_size;
  idx integer := 0;
  j integer;
  w text;
  l text;
  players text[] := array[]::text[];
  previous text[];
  current_winners text[];
  forwarded text;
  client text;
  recorded integer;
begin
  if p_size is null or p_size not in (8, 16, 32, 64) then
    raise exception 'WORLDCUP_INVALID_SIZE';
  end if;
  if p_matches is null or jsonb_typeof(p_matches) <> 'array' or jsonb_array_length(p_matches) <> p_size - 1 then
    raise exception 'WORLDCUP_INVALID_MATCHES';
  end if;
  while round_size >= 2 loop
    current_winners := array[]::text[];
    for j in 0 .. round_size / 2 - 1 loop
      if jsonb_typeof(p_matches -> idx) <> 'array' or jsonb_array_length(p_matches -> idx) <> 2 then
        raise exception 'WORLDCUP_INVALID_MATCH';
      end if;
      w := p_matches -> idx ->> 0;
      l := p_matches -> idx ->> 1;
      if w is null or l is null or w = l then
        raise exception 'WORLDCUP_INVALID_MATCH';
      end if;
      if round_size = p_size then
        players := players || w || l;
      elsif not ((w = previous[2 * j + 1] and l = previous[2 * j + 2])
                 or (w = previous[2 * j + 2] and l = previous[2 * j + 1])) then
        raise exception 'WORLDCUP_INVALID_BRACKET';
      end if;
      current_winners := current_winners || w;
      idx := idx + 1;
    end loop;
    previous := current_winners;
    round_size := round_size / 2;
  end loop;
  if (select count(distinct p) from unnest(players) p) <> p_size then
    raise exception 'WORLDCUP_INVALID_BRACKET';
  end if;
  if (select count(*) from public.worldcup_dish_stats where dish_id = any(players)) <> p_size then
    raise exception 'WORLDCUP_UNKNOWN_DISH';
  end if;

  forwarded := btrim(split_part(coalesce(current_setting('request.headers', true)::json ->> 'x-forwarded-for', ''), ',', 1));
  client := encode(extensions.digest((select salt from public.worldcup_secret) || current_date::text || forwarded, 'sha256'), 'hex');
  insert into public.worldcup_rate as r (client_hash, window_start, games)
    values (client, date_trunc('hour', now()), 1)
    on conflict (client_hash, window_start) do update set games = r.games + 1
    returning games into recorded;
  delete from public.worldcup_rate where window_start < now() - interval '1 day';
  if recorded > 30 then
    raise exception 'WORLDCUP_RATE_LIMITED';
  end if;

  update public.worldcup_dish_stats set entries = entries + 1, updated_at = now() where dish_id = any(players);
  update public.worldcup_dish_stats s set matches = s.matches + x.n, updated_at = now()
    from (select id, count(*) as n from (
            select value ->> 0 as id from jsonb_array_elements(p_matches)
            union all select value ->> 1 from jsonb_array_elements(p_matches)) m group by id) x
    where s.dish_id = x.id;
  update public.worldcup_dish_stats s set wins = s.wins + x.n
    from (select value ->> 0 as id, count(*) as n from jsonb_array_elements(p_matches) group by 1) x
    where s.dish_id = x.id;
  update public.worldcup_dish_stats set titles = titles + 1 where dish_id = previous[1];
  update public.worldcup_totals set games = games + 1, updated_at = now() where singleton = true;
end;
$$;
revoke all on function public.worldcup_record_game(integer, jsonb) from public;
grant execute on function public.worldcup_record_game(integer, jsonb) to anon, authenticated, service_role;
commit;
