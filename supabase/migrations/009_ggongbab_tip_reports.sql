-- 꽁밥 제보, in the visitor's own words (owner, 2026-11-01: "제보하기쪽에서 너무 많은 내용이 들어가야되는거 같아.
-- 사용자는 제보하는거고, 우리는 그거를 분류하는 사람이 되어야"). A visitor writes what they saw and may add
-- photos; the operations PC reads it with the Instagram radar's classifier model, fills in the event's
-- fields, and the owner confirms them in Telegram before anything reaches the board.
-- REVIEW AND APPLY MANUALLY in the Supabase SQL editor (after 008); application code never runs it.
-- docs/GGONGBAB_TIPS.md.
--
-- Nothing is widened for browsers: they still only call a checking function (now one more) and upload
-- photos for the tip they have just sent. ggongbab_submit_tip stays for a page loaded before this change.
begin;

-- A report has no event fields of its own; the operations PC writes them with the backend key.
alter table public.ggongbab_tips alter column title drop not null;
alter table public.ggongbab_tips alter column place drop not null;
alter table public.ggongbab_tips alter column event_date drop not null;
-- When the operations PC's model filled in title, place, event_date, time_text and food from the
-- visitor's words (null: the visitor typed those fields, or nobody has read the report yet).
alter table public.ggongbab_tips add column if not exists classified_at timestamptz;

-- One report: the visitor's words (up to 1000 characters) and how many photos will follow (0-3).
-- Either words (2 characters or more) or at least one photo. The same honeypot and limits as
-- ggongbab_submit_tip. Returns the id that names the photos' folder.
create or replace function public.ggongbab_submit_report(p_text text, p_photos integer, p_hp text)
returns uuid language plpgsql security definer set search_path = pg_catalog, public
as $$
declare
  today date := (now() at time zone 'Asia/Seoul')::date;
  v_text text := btrim(coalesce(p_text, ''));
  forwarded text;
  client text;
  recorded integer;
  tip_id uuid;
begin
  if btrim(coalesce(p_hp, '')) <> '' then
    return gen_random_uuid();
  end if;
  if char_length(v_text) > 1000 or p_photos is null or p_photos not between 0 and 3
     or (char_length(v_text) < 2 and p_photos < 1) then
    raise exception 'TIP_INVALID';
  end if;

  forwarded := btrim(split_part(coalesce(current_setting('request.headers', true)::json ->> 'x-forwarded-for', ''), ',', 1));
  client := encode(extensions.digest((select salt from public.ggongbab_tip_secret) || today::text || forwarded, 'sha256'), 'hex');
  insert into public.ggongbab_tip_rate as r (client_hash, window_start, tips)
    values (client, date_trunc('hour', now()), 1)
    on conflict (client_hash, window_start) do update set tips = r.tips + 1
    returning tips into recorded;
  delete from public.ggongbab_tip_rate where window_start < now() - interval '1 day';
  if recorded > 5 then
    raise exception 'TIP_RATE_LIMITED';
  end if;
  if (select count(*) from public.ggongbab_tips where created_at > now() - interval '1 day') >= 60 then
    raise exception 'TIP_RATE_LIMITED';
  end if;

  insert into public.ggongbab_tips (details, client_hash)
    values (v_text, client)
    returning id into tip_id;
  return tip_id;
end;
$$;
revoke all on function public.ggongbab_submit_report(text, integer, text) from public;
grant execute on function public.ggongbab_submit_report(text, integer, text) to anon, authenticated, service_role;
commit;
