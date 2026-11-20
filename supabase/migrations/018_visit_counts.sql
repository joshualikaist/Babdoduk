-- 방문 수 (owner 2026-11-20: "내 사이트를 언제 제일 많이 이용하는지, 어디 콘텐츠가 반응이 좋은지"; "오케이").
-- REVIEW AND APPLY MANUALLY in the Supabase SQL editor (after 017); application code never runs it.
-- docs/USAGE_STATS.md.
--
-- Stored: per hour only which of our sites, which page, the page's language, phone/tablet/computer and how
-- many times a page was opened. No row per person or per visit, no address, no cookie, no account, no
-- user agent: a count cannot be traced back to anyone. The browser never calls the database for this: the
-- site's own /api/visit (api/visit.js) calls count_visit with the publishable key. Only the backend key
-- reads the counts (scripts/usage_stats.py report).
begin;

-- The pages that may be counted, so a direct call cannot invent rows. A new page is added with
-- python scripts/usage_stats.py pages (backend key).
create table if not exists public.visit_pages (
  page text primary key check (page ~ '^[a-z0-9]+(-[a-z0-9]+)*$' and length(page) <= 40)
);
insert into public.visit_pages(page) values
  ('index'), ('ggongbab'), ('event'), ('history'), ('mukbang'), ('choose'), ('worldcup'), ('my'), ('tip'),
  ('privacy'), ('bobyak'), ('cardnews'), ('food'), ('lab'), ('lab-ggongbab')
on conflict do nothing;
alter table public.visit_pages enable row level security;
revoke all on table public.visit_pages from public, anon, authenticated;
grant select, insert on table public.visit_pages to service_role;

create table if not exists public.visit_counts (
  hour timestamptz not null check (date_trunc('hour', hour) = hour),
  site text not null check (site in ('www.babdodukms.com', 'babdoduk.vercel.app', 'babdoduk-lab.vercel.app')),
  page text not null references public.visit_pages (page),
  lang text not null check (lang in ('ko', 'en')),
  device text not null check (device in ('phone', 'tablet', 'computer')),
  views bigint not null default 0 check (views >= 0),
  primary key (hour, site, page, lang, device)
);
alter table public.visit_counts enable row level security;
revoke all on table public.visit_counts from public, anon, authenticated;
grant select on table public.visit_counts to service_role;

-- One page opened: adds one to this hour's count. SECURITY DEFINER so the anon role reaches the counts only
-- through it; the hour is the database's clock, never the caller's.
create or replace function public.count_visit(p_site text, p_page text, p_lang text, p_device text)
returns void language plpgsql security definer set search_path = ''
as $$
begin
  if p_site is null or p_site not in ('www.babdodukms.com', 'babdoduk.vercel.app', 'babdoduk-lab.vercel.app')
     or p_lang is null or p_lang not in ('ko', 'en')
     or p_device is null or p_device not in ('phone', 'tablet', 'computer')
     or p_page is null or not exists (select 1 from public.visit_pages v where v.page = p_page) then
    raise exception 'VISIT_INVALID';
  end if;
  insert into public.visit_counts as c (hour, site, page, lang, device, views)
    values (date_trunc('hour', now()), p_site, p_page, p_lang, p_device, 1)
    on conflict (hour, site, page, lang, device) do update set views = c.views + 1;
end;
$$;
revoke all on function public.count_visit(text, text, text, text) from public;
grant execute on function public.count_visit(text, text, text, text) to anon;
commit;
