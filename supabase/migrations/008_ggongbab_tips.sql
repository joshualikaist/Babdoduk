-- 꽁밥 제보 게시판 (owner, 2026-10-31): visitors tip offline free-food events the radars missed.
-- REVIEW AND APPLY MANUALLY in the Supabase SQL editor (after 006); application code never runs it.
-- docs/GGONGBAB_TIPS.md.
--
-- A browser can only send a tip through ggongbab_submit_tip, which checks it and limits how often,
-- and upload up to three photos for the tip it has just sent (a private bucket, insert only, for 15
-- minutes). It can read neither tips nor photos. The board (ggongbab_tip_board) holds only what the
-- owner confirmed in Telegram, written by the operations PC with the backend key: title, place, date,
-- time and food. Never the details, the link, the photos or anything about the sender.
begin;

create extension if not exists pgcrypto with schema extensions;

create table if not exists public.ggongbab_tips (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  title text not null check (char_length(title) between 2 and 80),
  place text not null check (char_length(place) between 1 and 80),
  event_date date not null,
  time_text text not null default '' check (char_length(time_text) <= 40),
  food text not null default '' check (char_length(food) <= 120),
  details text not null default '' check (char_length(details) <= 1000),
  link text check (link is null or (char_length(link) <= 300 and link ~ '^https?://')),
  image_count smallint not null default 0 check (image_count between 0 and 3),
  client_hash text not null,
  status text not null default 'new' check (status in ('new', 'accepted', 'rejected')),
  notified_at timestamptz,
  reviewed_at timestamptz,
  dooray_post_id text
);
create index if not exists ggongbab_tips_status_created on public.ggongbab_tips (status, created_at);
alter table public.ggongbab_tips enable row level security;
revoke all on table public.ggongbab_tips from public, anon, authenticated;
grant select, update on table public.ggongbab_tips to service_role;

-- The public board: a confirmed tip, as the owner accepted it.
create table if not exists public.ggongbab_tip_board (
  id uuid primary key references public.ggongbab_tips (id) on delete cascade,
  title text not null check (char_length(title) between 2 and 80),
  place text not null check (char_length(place) between 1 and 80),
  event_date date not null,
  time_text text not null default '' check (char_length(time_text) <= 40),
  food text not null default '' check (char_length(food) <= 120),
  accepted_at timestamptz not null default now()
);
create index if not exists ggongbab_tip_board_date on public.ggongbab_tip_board (event_date);
alter table public.ggongbab_tip_board enable row level security;
revoke all on table public.ggongbab_tip_board from public, anon, authenticated;
grant select on table public.ggongbab_tip_board to anon, authenticated;
grant select, insert, update, delete on table public.ggongbab_tip_board to service_role;
drop policy if exists ggongbab_tip_board_read on public.ggongbab_tip_board;
create policy ggongbab_tip_board_read on public.ggongbab_tip_board for select to anon, authenticated using (true);

-- Abuse limit: at most 5 tips per client per hour, and 60 tips in any 24 hours overall. The client
-- is a salted hash of the forwarded address and the Korean date (the salt never leaves the
-- database); rate rows go after a day.
create table if not exists public.ggongbab_tip_secret (
  singleton boolean primary key default true check (singleton),
  salt text not null default encode(extensions.gen_random_bytes(32), 'hex')
);
insert into public.ggongbab_tip_secret(singleton) values (true) on conflict do nothing;
alter table public.ggongbab_tip_secret enable row level security;
revoke all on table public.ggongbab_tip_secret from public, anon, authenticated, service_role;

create table if not exists public.ggongbab_tip_rate (
  client_hash text not null,
  window_start timestamptz not null,
  tips integer not null default 0,
  primary key (client_hash, window_start)
);
alter table public.ggongbab_tip_rate enable row level security;
revoke all on table public.ggongbab_tip_rate from public, anon, authenticated, service_role;

-- One tip. Returns its id, which names the folder its photos go to. A filled honeypot (a field
-- people never see) is a bot: it gets an id like anyone else, and nothing is stored.
-- SECURITY DEFINER so the browser roles reach the table only through these checks.
create or replace function public.ggongbab_submit_tip(p_title text, p_place text, p_event_date date,
                                                      p_time_text text, p_food text, p_details text,
                                                      p_link text, p_hp text)
returns uuid language plpgsql security definer set search_path = pg_catalog, public
as $$
declare
  today date := (now() at time zone 'Asia/Seoul')::date;
  v_title text := btrim(coalesce(p_title, ''));
  v_place text := btrim(coalesce(p_place, ''));
  v_time text := btrim(coalesce(p_time_text, ''));
  v_food text := btrim(coalesce(p_food, ''));
  v_details text := btrim(coalesce(p_details, ''));
  v_link text := nullif(btrim(coalesce(p_link, '')), '');
  forwarded text;
  client text;
  recorded integer;
  tip_id uuid;
begin
  if btrim(coalesce(p_hp, '')) <> '' then
    return gen_random_uuid();
  end if;
  if char_length(v_title) not between 2 and 80
     or char_length(v_place) not between 1 and 80
     or p_event_date is null or p_event_date not between today - 1 and today + 60
     or char_length(v_time) > 40 or char_length(v_food) > 120 or char_length(v_details) > 1000
     or (v_link is not null and (char_length(v_link) > 300 or v_link !~ '^https?://[^[:space:]]+$')) then
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

  insert into public.ggongbab_tips (title, place, event_date, time_text, food, details, link, client_hash)
    values (v_title, v_place, p_event_date, v_time, v_food, v_details, v_link, client)
    returning id into tip_id;
  return tip_id;
end;
$$;
revoke all on function public.ggongbab_submit_tip(text, text, date, text, text, text, text, text) from public;
grant execute on function public.ggongbab_submit_tip(text, text, date, text, text, text, text, text) to anon, authenticated, service_role;

-- Photos (a poster, the place): a private bucket. Never public, never shown on the board; the
-- owner sees them in the review, and operations deletes a tip's photos 14 days after the review.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
  values ('ggongbab-tip-images', 'ggongbab-tip-images', false, 5242880, array['image/jpeg', 'image/png', 'image/webp'])
  on conflict (id) do update set public = false, file_size_limit = excluded.file_size_limit,
                                 allowed_mime_types = excluded.allowed_mime_types;

-- A browser may add a photo only as <tip id>/<1|2|3>.<jpg|png|webp>, for a tip that is still new and
-- was sent in the last 15 minutes, while that folder holds fewer than three photos. SECURITY
-- DEFINER because the browser roles cannot read the tips or the bucket themselves.
create or replace function public.ggongbab_tip_upload_allowed(p_name text)
returns boolean language plpgsql stable security definer set search_path = pg_catalog, public
as $$
declare
  folder text;
begin
  if p_name is null
     or p_name !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/[123]\.(jpg|png|webp)$' then
    return false;
  end if;
  folder := split_part(p_name, '/', 1);
  if not exists (select 1 from public.ggongbab_tips t where t.id = folder::uuid and t.status = 'new'
                 and t.created_at > now() - interval '15 minutes') then
    return false;
  end if;
  return (select count(*) from storage.objects o
          where o.bucket_id = 'ggongbab-tip-images' and o.name like folder || '/%') < 3;
end;
$$;
revoke all on function public.ggongbab_tip_upload_allowed(text) from public;
grant execute on function public.ggongbab_tip_upload_allowed(text) to anon, authenticated, service_role;

drop policy if exists ggongbab_tip_images_insert on storage.objects;
create policy ggongbab_tip_images_insert on storage.objects for insert to anon, authenticated
  with check (bucket_id = 'ggongbab-tip-images' and public.ggongbab_tip_upload_allowed(name));
drop policy if exists ggongbab_tip_images_backend on storage.objects;
create policy ggongbab_tip_images_backend on storage.objects for all to service_role
  using (bucket_id = 'ggongbab-tip-images') with check (bucket_id = 'ggongbab-tip-images');
commit;
