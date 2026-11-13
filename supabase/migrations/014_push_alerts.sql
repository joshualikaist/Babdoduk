-- 별 누른 꽁밥 30분 전 알림 (owner 2026-11-12, "오케이 너무 좋다 그러면"; docs/PUSH_ALERTS.md).
-- REVIEW AND APPLY MANUALLY in the Supabase SQL editor. Application code never runs it.
--
-- A phone that opened the site from its home screen (or any browser with web push) turns the alert on
-- once. The browser then keeps one row here: its push address (endpoint and the two public keys the push
-- standard needs to encrypt a message to it), the ids of the free-food events it starred, its language
-- and which of our sites it uses. No account, name, email or IP is stored. The ops computer reads these
-- rows with the backend key and sends one message 30 minutes before each starred event
-- (scripts/push/send.js, docs/PUSH_ALERTS.md).
--
-- Browsers get two checking functions and nothing else: no table is readable or writable by anon or
-- authenticated. The endpoint is the device's own key: it is a long random address that only that
-- browser and its push service know.
begin;

create table if not exists public.push_devices (
  endpoint text primary key check (
    char_length(endpoint) <= 1000
    and endpoint ~ '^https://(web\.push\.apple\.com|fcm\.googleapis\.com|updates\.push\.services\.mozilla\.com|[a-z0-9-]+\.notify\.windows\.com)/[A-Za-z0-9_:/.=%~+?&-]+$'),
  p256dh text not null check (p256dh ~ '^[A-Za-z0-9_-]{86,88}$'),
  auth text not null check (auth ~ '^[A-Za-z0-9_-]{21,24}$'),
  events text[] not null default '{}' check (cardinality(events) <= 300),
  lang text not null default 'ko' check (lang in ('ko', 'en')),
  site text not null check (site in ('https://babdoduk-lab.vercel.app', 'https://babdoduk.vercel.app', 'https://www.babdodukms.com')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  failures integer not null default 0
);
create index if not exists push_devices_events on public.push_devices using gin (events);
alter table public.push_devices enable row level security;
revoke all on table public.push_devices from public, anon, authenticated, service_role;
-- The ops computer's sender: read the devices, count failures, drop a device its push service no longer knows.
grant select, update, delete on table public.push_devices to service_role;

-- Turn on, or update the starred list of, this browser. Ids that do not look like a listing id are
-- dropped, not refused, so one odd saved row never stops the rest. Abuse limits: at most 500 new
-- devices in any 24 hours and 50 000 in all; an existing device can always update itself.
create or replace function public.push_device_save(p_endpoint text, p_p256dh text, p_auth text,
                                                   p_events text[], p_lang text, p_site text)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  clean text[];
begin
  select coalesce(array_agg(distinct e), '{}') into clean
    from (select e from unnest(coalesce(p_events, '{}')) as e
           where e ~ '^[A-Za-z0-9_-]{1,80}(#[0-9]{1,2})?$' limit 300) as ids;
  if not exists (select 1 from public.push_devices where endpoint = p_endpoint) then
    if (select count(*) from public.push_devices where created_at > now() - interval '1 day') >= 500
       or (select count(*) from public.push_devices) >= 50000 then
      raise exception 'PUSH_DEVICE_LIMIT';
    end if;
  end if;
  insert into public.push_devices as d (endpoint, p256dh, auth, events, lang, site)
    values (p_endpoint, p_p256dh, p_auth, clean, coalesce(p_lang, 'ko'), p_site)
  on conflict (endpoint) do update
    set p256dh = excluded.p256dh, auth = excluded.auth, events = excluded.events, lang = excluded.lang,
        site = excluded.site, updated_at = now(), failures = 0;
  return true;
end;
$$;

-- Turn off this browser: its row goes.
create or replace function public.push_device_remove(p_endpoint text)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
begin
  delete from public.push_devices where endpoint = p_endpoint;
  return found;
end;
$$;

revoke all on function public.push_device_save(text, text, text, text[], text, text), public.push_device_remove(text)
  from public, anon, authenticated;
grant execute on function public.push_device_save(text, text, text, text[], text, text) to anon, authenticated;
grant execute on function public.push_device_remove(text) to anon, authenticated;

commit;
