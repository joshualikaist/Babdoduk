-- PROPOSAL ONLY: requires explicit owner authorization for this new table, RLS and RPCs.
-- After approval, reserve the next migration number, move this into supabase/migrations/,
-- and apply manually in the SQL editor. No existing tables or policies are changed.
begin;
create table public.panel_live_snapshot (
  id boolean primary key default true check (id),
  timeline jsonb not null check (
    jsonb_typeof(timeline) = 'object'
    and jsonb_typeof(timeline -> 'events') = 'array'
    and jsonb_typeof(timeline -> 'panes') = 'array'
    and jsonb_array_length(timeline -> 'events') <= 10000
    and octet_length(timeline::text) <= 2000000
  ),
  updated_at timestamptz not null
);
alter table public.panel_live_snapshot enable row level security;
revoke all on table public.panel_live_snapshot from public, anon, authenticated;

-- Only the operations computer may write. Older uploads cannot overwrite a newer run.
create function public.panel_live_publish(p_timeline jsonb, p_updated_at timestamptz)
returns void language sql security definer set search_path = '' as $$
  insert into public.panel_live_snapshot as s (id, timeline, updated_at)
    values (true, p_timeline, p_updated_at)
  on conflict (id) do update set timeline = excluded.timeline, updated_at = excluded.updated_at
    where s.updated_at <= excluded.updated_at;
$$;
revoke all on function public.panel_live_publish(jsonb, timestamptz) from public, anon, authenticated;
grant execute on function public.panel_live_publish(jsonb, timestamptz) to service_role;

-- Only this already sanitized public snapshot may be read with the publishable key.
-- Public RPCs are directly addressable; the lab-only page and relay route are not authentication.
create function public.panel_live_read()
returns jsonb language sql stable security definer set search_path = '' as $$
  select jsonb_build_object('updatedAt', updated_at, 'timeline', timeline)
  from public.panel_live_snapshot where id = true;
$$;
revoke all on function public.panel_live_read() from public;
grant execute on function public.panel_live_read() to anon, authenticated;
commit;
