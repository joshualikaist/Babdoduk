-- 밥약 메이커 식당 제보 (밥도둑 2.0 phase 3, Q9; docs/BOBYAK.md): a visitor tells us a place's details are
-- wrong, it closed, or adds a tip. Nothing a visitor sends reaches the site by itself: the operator reads
-- the reports with the backend key and changes data/places/ through inputs/places/approvals.json.
-- DRAFT, NOT APPLIED. REVIEW AND APPLY MANUALLY in the Supabase SQL editor (after 008, whose salt it reuses),
-- only with the owner's approval (Q30); application code never runs it. No page calls it yet.
--
-- Browsers get one checking function and nothing else: no table is readable or writable by anon or
-- authenticated, and there is no public board for place reports (Q9: no public reviews or ratings).
begin;

create table if not exists public.place_reports (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  -- The site's own place id (data/places/latest.json), or null for "a place you don't list".
  place_id text check (place_id is null or place_id ~ '^p-[0-9a-z]{4,24}$'),
  kind text not null check (kind in ('wrong', 'closed', 'new', 'tip')),
  details text not null check (char_length(details) between 2 and 600),
  client_hash text not null,
  status text not null default 'new' check (status in ('new', 'accepted', 'rejected')),
  reviewed_at timestamptz
);
create index if not exists place_reports_status_created on public.place_reports (status, created_at);
alter table public.place_reports enable row level security;
revoke all on table public.place_reports from public, anon, authenticated;
grant select, update on table public.place_reports to service_role;

-- Abuse limit: at most 5 reports per client per hour and 100 in any 24 hours overall. The client is the
-- same salted hash of the forwarded address and the Korean date as the free-food tips (008); rate rows
-- go after a day.
create table if not exists public.place_report_rate (
  client_hash text not null,
  window_start timestamptz not null,
  reports integer not null default 0,
  primary key (client_hash, window_start)
);
alter table public.place_report_rate enable row level security;
revoke all on table public.place_report_rate from public, anon, authenticated, service_role;

-- One report. A filled honeypot is a bot: it gets an id like anyone else, and nothing is stored.
-- SECURITY DEFINER so the browser roles reach the table only through these checks.
create or replace function public.place_submit_report(p_place_id text, p_kind text, p_details text, p_hp text)
returns uuid language plpgsql security definer set search_path = pg_catalog, public
as $$
declare
  today date := (now() at time zone 'Asia/Seoul')::date;
  v_details text := btrim(coalesce(p_details, ''));
  v_place text := nullif(btrim(coalesce(p_place_id, '')), '');
  forwarded text;
  client text;
  recorded integer;
  report_id uuid;
begin
  if btrim(coalesce(p_hp, '')) <> '' then
    return gen_random_uuid();
  end if;
  if p_kind is null or p_kind not in ('wrong', 'closed', 'new', 'tip')
     or char_length(v_details) not between 2 and 600
     or (v_place is not null and v_place !~ '^p-[0-9a-z]{4,24}$') then
    raise exception 'PLACE_REPORT_INVALID';
  end if;

  forwarded := btrim(split_part(coalesce(current_setting('request.headers', true)::json ->> 'x-forwarded-for', ''), ',', 1));
  client := encode(extensions.digest((select salt from public.ggongbab_tip_secret) || today::text || forwarded, 'sha256'), 'hex');
  insert into public.place_report_rate as r (client_hash, window_start, reports)
    values (client, date_trunc('hour', now()), 1)
    on conflict (client_hash, window_start) do update set reports = r.reports + 1
    returning reports into recorded;
  delete from public.place_report_rate where window_start < now() - interval '1 day';
  if recorded > 5 then
    raise exception 'PLACE_REPORT_RATE_LIMITED';
  end if;
  if (select count(*) from public.place_reports where created_at > now() - interval '1 day') >= 100 then
    raise exception 'PLACE_REPORT_RATE_LIMITED';
  end if;

  insert into public.place_reports (place_id, kind, details, client_hash)
    values (v_place, p_kind, v_details, client)
    returning id into report_id;
  return report_id;
end;
$$;
revoke all on function public.place_submit_report(text, text, text, text) from public;
grant execute on function public.place_submit_report(text, text, text, text) to anon, authenticated, service_role;
commit;
