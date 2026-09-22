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
