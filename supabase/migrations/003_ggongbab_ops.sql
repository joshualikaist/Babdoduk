-- Operator metadata for the resident Dooray agent, and a private conflict log.
-- Apply after 002. Safe to re-run.
--
-- agent_heartbeats holds scan status only. Do not add mail subject, sender,
-- body, preview, cookie, token, or profile columns.
-- event_conflicts records a disputed merge without unpublishing the event.
-- Neither table is readable by the browser.

create table if not exists public.agent_heartbeats (
  agent_id              text primary key,
  last_scan_at          timestamptz,
  last_success_at       timestamptz,
  last_publish_at       timestamptz,
  status                text not null
                        check (status in ('healthy', 'auth_required', 'ui_changed',
                                          'collector_error', 'pipeline_error')),
  exit_class            text not null default '',
  auth_required         boolean not null default false,
  ui_contract_changed   boolean not null default false,
  version               text not null default '',
  updated_at            timestamptz not null default now()
);

create table if not exists public.event_conflicts (
  id           uuid primary key default gen_random_uuid(),
  event_id     uuid not null references public.events(id) on delete cascade,
  raw_item_id  uuid references public.raw_items(id) on delete set null,
  summary      text not null,
  created_at   timestamptz not null default now()
);
create index if not exists event_conflicts_event_idx on public.event_conflicts (event_id, created_at desc);

alter table public.agent_heartbeats enable row level security;
alter table public.event_conflicts enable row level security;

revoke all on public.agent_heartbeats, public.event_conflicts from anon, authenticated;

-- A plain upsert does not refresh updated_at, and a null in the payload would
-- erase the previous success or publish time. One statement keeps the newer
-- timestamp and ignores a stale scan's status.
create or replace function public.ggongbab_record_heartbeat(
  p_agent_id text,
  p_last_scan_at timestamptz,
  p_last_success_at timestamptz,
  p_last_publish_at timestamptz,
  p_status text,
  p_exit_class text,
  p_auth_required boolean,
  p_ui_contract_changed boolean,
  p_version text
) returns void
language plpgsql
as $$
begin
  insert into public.agent_heartbeats as h (
    agent_id, last_scan_at, last_success_at, last_publish_at,
    status, exit_class, auth_required, ui_contract_changed, version
  ) values (
    p_agent_id, p_last_scan_at, p_last_success_at, p_last_publish_at,
    p_status, coalesce(p_exit_class, ''), coalesce(p_auth_required, false),
    coalesce(p_ui_contract_changed, false), coalesce(p_version, '')
  )
  on conflict (agent_id) do update set
    last_scan_at = case
      when h.last_scan_at is null then excluded.last_scan_at
      when excluded.last_scan_at is null then h.last_scan_at
      else greatest(h.last_scan_at, excluded.last_scan_at)
    end,
    last_success_at = case
      when excluded.last_success_at is null then h.last_success_at
      when h.last_success_at is null then excluded.last_success_at
      else greatest(h.last_success_at, excluded.last_success_at)
    end,
    last_publish_at = case
      when excluded.last_publish_at is null then h.last_publish_at
      when h.last_publish_at is null then excluded.last_publish_at
      else greatest(h.last_publish_at, excluded.last_publish_at)
    end,
    status = case
      when excluded.last_scan_at < h.last_scan_at then h.status
      else excluded.status
    end,
    exit_class = case
      when excluded.last_scan_at < h.last_scan_at then h.exit_class
      else excluded.exit_class
    end,
    auth_required = case
      when excluded.last_scan_at < h.last_scan_at then h.auth_required
      else excluded.auth_required
    end,
    ui_contract_changed = case
      when excluded.last_scan_at < h.last_scan_at then h.ui_contract_changed
      else excluded.ui_contract_changed
    end,
    version = case
      when excluded.last_scan_at < h.last_scan_at then h.version
      else excluded.version
    end;
end;
$$;

revoke all on function public.ggongbab_record_heartbeat(
  text, timestamptz, timestamptz, timestamptz, text, text, boolean, boolean, text
) from public, anon, authenticated;

drop trigger if exists agent_heartbeats_touch_updated_at on public.agent_heartbeats;
create trigger agent_heartbeats_touch_updated_at
  before update on public.agent_heartbeats
  for each row execute function public.ggongbab_touch_updated_at();

-- Do not rely on Supabase default privileges. anon and authenticated stay revoked.
-- service_role is the backend role that calls the heartbeat RPC and writes conflicts.
grant select, insert, update on table public.agent_heartbeats to service_role;
grant select, insert on table public.event_conflicts to service_role;
grant execute on function public.ggongbab_record_heartbeat(
  text, timestamptz, timestamptz, timestamptz, text, text, boolean, boolean, text
) to service_role;

