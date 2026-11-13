-- 꽁밥 알림 보안 보강 (security audit 2026-11-13, owner "그 부분 빼고 다 진행해"; docs/PUSH_ALERTS.md).
-- REVIEW AND APPLY MANUALLY in the Supabase SQL editor, after 008 and 014. Application code never runs it.
-- Applying it twice is harmless.
--
-- Two things 014 left open to anyone with the site's public key:
--
-- 1. Key shape. 014 accepted any 86-88 / 21-24 character string as a browser's two push keys. A real
--    browser key (p256dh) is an uncompressed P-256 point, 65 bytes starting with 0x04, which is exactly 87
--    base64url characters starting with "B"; the auth secret is 16 bytes, exactly 22 characters. Rows of any
--    other shape cannot be encrypted to and can only have come from something other than a browser, so they
--    are deleted before the tighter checks go on (a real phone that somehow lost its row stores itself again
--    on its next daily resend, js/ggongbab-push.js).
--
-- 2. Who adds devices. 014 capped new devices only globally (500 a day, 50 000 in all), so one visitor
--    could use up the day's 500 and lock everyone else out. Now each visitor may add at most 5 new devices
--    an hour and 20 a Korean day. The visitor is the same salted hash of the first forwarded address and the
--    Korean date as the free-food tips (008) and place reports (012), with 008's salt; no address is stored.
--    The global caps stay. Updating a device that is already there (a new star list, a new language) is
--    never limited.
begin;

-- 1. Key shape ----------------------------------------------------------------------------------------------
delete from public.push_devices
 where p256dh !~ '^B[A-Za-z0-9_-]{86}$' or auth !~ '^[A-Za-z0-9_-]{22}$';
alter table public.push_devices drop constraint if exists push_devices_p256dh_check;
alter table public.push_devices add constraint push_devices_p256dh_check check (p256dh ~ '^B[A-Za-z0-9_-]{86}$');
alter table public.push_devices drop constraint if exists push_devices_auth_check;
alter table public.push_devices add constraint push_devices_auth_check check (auth ~ '^[A-Za-z0-9_-]{22}$');

-- 2. New devices per visitor ----------------------------------------------------------------------------------
-- One row per visitor hash and hour; rows go after a day. Closed to every API role: only the function below
-- (security definer) touches it.
create table if not exists public.push_device_rate (
  client_hash text not null,
  window_start timestamptz not null,
  devices integer not null default 0,
  primary key (client_hash, window_start)
);
alter table public.push_device_rate enable row level security;
revoke all on table public.push_device_rate from public, anon, authenticated, service_role;

-- 014's function, with the per-visitor limit before the global caps. Same signature, same grants.
create or replace function public.push_device_save(p_endpoint text, p_p256dh text, p_auth text,
                                                   p_events text[], p_lang text, p_site text)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  clean text[];
  today date := (now() at time zone 'Asia/Seoul')::date;
  forwarded text;
  client text;
  hourly integer;
  daily integer;
begin
  select coalesce(array_agg(distinct e), '{}') into clean
    from (select e from unnest(coalesce(p_events, '{}')) as e
           where e ~ '^[A-Za-z0-9_-]{1,80}(#[0-9]{1,2})?$' limit 300) as ids;
  if not exists (select 1 from public.push_devices where endpoint = p_endpoint) then
    forwarded := btrim(split_part(coalesce(current_setting('request.headers', true)::json ->> 'x-forwarded-for', ''), ',', 1));
    client := encode(extensions.digest((select salt from public.ggongbab_tip_secret) || today::text || forwarded, 'sha256'), 'hex');
    insert into public.push_device_rate as r (client_hash, window_start, devices)
      values (client, date_trunc('hour', now()), 1)
      on conflict (client_hash, window_start) do update set devices = r.devices + 1
      returning devices into hourly;
    delete from public.push_device_rate where window_start < now() - interval '1 day';
    -- The hash holds the Korean date, so all of a hash's rows are that one day's.
    select coalesce(sum(devices), 0) into daily from public.push_device_rate where client_hash = client;
    if hourly > 5 or daily > 20 then
      raise exception 'PUSH_DEVICE_RATE_LIMITED';
    end if;
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

revoke all on function public.push_device_save(text, text, text, text[], text, text) from public, anon, authenticated;
grant execute on function public.push_device_save(text, text, text, text[], text, text) to anon, authenticated;

commit;
