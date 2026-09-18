-- Babdoduk 꽁밥 (free food event) collection schema.
-- Canonical store for collected raw mail/notices, AI parse runs and merged events.
-- Apply with: supabase db push  (or paste into the SQL editor of the project).

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- sources: where raw items come from (dooray project, kaist public site, manual file, portal)
-- ---------------------------------------------------------------------------
create table if not exists public.sources (
  id          uuid primary key default gen_random_uuid(),
  type        text not null check (type in ('dooray', 'kaist_public', 'manual', 'portal')),
  name        text not null,
  priority    integer not null default 100,
  enabled     boolean not null default true,
  created_at  timestamptz not null default now(),
  unique (type, name)
);

-- ---------------------------------------------------------------------------
-- raw_items: one row per collected post / notice / manual entry. PRIVATE.
-- ---------------------------------------------------------------------------
create table if not exists public.raw_items (
  id                 uuid primary key default gen_random_uuid(),
  source_id          uuid not null references public.sources(id) on delete restrict,
  external_id        text not null,
  subject            text,
  sender_name        text,
  sender_email       text,
  raw_text           text,
  raw_html           text,
  source_url         text,
  source_created_at  timestamptz,
  source_updated_at  timestamptz,
  content_hash       text not null,
  metadata           jsonb not null default '{}'::jsonb,
  ingested_at        timestamptz not null default now(),
  last_seen_at       timestamptz not null default now(),
  unique (source_id, external_id)
);
create index if not exists raw_items_content_hash_idx on public.raw_items (content_hash);
create index if not exists raw_items_source_created_idx on public.raw_items (source_created_at desc);

-- ---------------------------------------------------------------------------
-- attachments: files referenced by a raw item (posters). PRIVATE.
-- ---------------------------------------------------------------------------
create table if not exists public.attachments (
  id               uuid primary key default gen_random_uuid(),
  raw_item_id      uuid not null references public.raw_items(id) on delete cascade,
  external_file_id text not null,
  filename         text,
  mime_type        text,
  size             bigint,
  sha256           text,
  parse_status     text not null default 'pending'
                   check (parse_status in ('pending', 'downloaded', 'skipped', 'failed', 'used')),
  metadata         jsonb not null default '{}'::jsonb,
  created_at       timestamptz not null default now(),
  unique (raw_item_id, external_file_id)
);

-- ---------------------------------------------------------------------------
-- ai_parse_runs: every OpenAI call (primary + fallback) with token usage. PRIVATE.
-- ---------------------------------------------------------------------------
create table if not exists public.ai_parse_runs (
  id                  uuid primary key default gen_random_uuid(),
  raw_item_id         uuid not null references public.raw_items(id) on delete cascade,
  content_hash        text,
  model               text not null,
  prompt_version      text not null,
  input_kind          text not null check (input_kind in ('text', 'text+image')),
  role                text not null default 'primary' check (role in ('primary', 'fallback')),
  parsed_json         jsonb,
  confidence          double precision,
  needs_review        boolean,
  usage_input_tokens  integer,
  usage_output_tokens integer,
  status              text not null check (status in ('ok', 'error')),
  error_message       text,
  created_at          timestamptz not null default now()
);
create index if not exists ai_parse_runs_raw_item_idx on public.ai_parse_runs (raw_item_id, created_at desc);
create index if not exists ai_parse_runs_hash_idx on public.ai_parse_runs (content_hash);

-- ---------------------------------------------------------------------------
-- events: merged, validated events. Only status=published & needs_review=false are exported.
-- ---------------------------------------------------------------------------
create table if not exists public.events (
  id                    uuid primary key default gen_random_uuid(),
  title                 text not null,
  summary               text,
  event_start           timestamptz,
  event_end             timestamptz,
  registration_deadline timestamptz,
  date_text             text,
  time_text             text,
  location_name         text,
  building              text,
  room                  text,
  food_provided         text not null default 'unknown' check (food_provided in ('true', 'false', 'unknown')),
  food_type             text not null default 'unknown'
                        check (food_type in ('meal', 'lunchbox', 'snack', 'refreshment', 'beverage', 'coupon', 'other', 'unknown')),
  food_description      text,
  organizer             text,
  eligibility           text,
  registration_required text not null default 'unknown' check (registration_required in ('true', 'false', 'unknown')),
  registration_url      text,
  confidence            double precision not null default 0,
  needs_review          boolean not null default false,
  review_reason         text,
  status                text not null default 'draft'
                        check (status in ('draft', 'published', 'review', 'rejected', 'archived')),
  dedup_key             text,
  first_seen_at         timestamptz not null default now(),
  last_seen_at          timestamptz not null default now(),
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);
create index if not exists events_event_start_idx on public.events (event_start);
create index if not exists events_status_idx on public.events (status);
create index if not exists events_needs_review_idx on public.events (needs_review);
create index if not exists events_dedup_key_idx on public.events (dedup_key);

-- ---------------------------------------------------------------------------
-- event_sources: N raw items can back one event (Dooray + KAIST notice + manual).
-- ---------------------------------------------------------------------------
create table if not exists public.event_sources (
  event_id     uuid not null references public.events(id) on delete cascade,
  raw_item_id  uuid not null references public.raw_items(id) on delete cascade,
  match_score  double precision,
  created_at   timestamptz not null default now(),
  primary key (event_id, raw_item_id)
);
create unique index if not exists event_sources_unique_idx on public.event_sources (event_id, raw_item_id);
create index if not exists event_sources_raw_item_idx on public.event_sources (raw_item_id);

-- ---------------------------------------------------------------------------
-- ingest_runs: one row per refresh execution (per source type) for observability.
-- ---------------------------------------------------------------------------
create table if not exists public.ingest_runs (
  id              uuid primary key default gen_random_uuid(),
  source_type     text not null,
  started_at      timestamptz not null default now(),
  finished_at     timestamptz,
  status          text not null default 'running' check (status in ('running', 'ok', 'failed', 'partial')),
  items_seen      integer not null default 0,
  items_new       integer not null default 0,
  events_created  integer not null default 0,
  events_updated  integer not null default 0,
  events_review   integer not null default 0,
  ai_calls        integer not null default 0,
  ai_skipped      integer not null default 0,
  ai_fallback     integer not null default 0,
  error_message   text
);
create index if not exists ingest_runs_started_idx on public.ingest_runs (started_at desc);

-- ---------------------------------------------------------------------------
-- updated_at trigger
-- ---------------------------------------------------------------------------
create or replace function public.ggongbab_touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists events_touch_updated_at on public.events;
create trigger events_touch_updated_at
  before update on public.events
  for each row execute function public.ggongbab_touch_updated_at();

-- ---------------------------------------------------------------------------
-- Security: everything is private. Only the service role (backend jobs) may read/write.
-- The browser never talks to this database; it reads data/ggongbab/latest.json instead.
-- ---------------------------------------------------------------------------
alter table public.sources        enable row level security;
alter table public.raw_items      enable row level security;
alter table public.attachments    enable row level security;
alter table public.ai_parse_runs  enable row level security;
alter table public.events         enable row level security;
alter table public.event_sources  enable row level security;
alter table public.ingest_runs    enable row level security;

revoke all on public.sources, public.raw_items, public.attachments, public.ai_parse_runs,
           public.events, public.event_sources, public.ingest_runs from anon, authenticated;
-- No policies are created on purpose: with RLS enabled and no policy, anon/authenticated get nothing.
-- service_role bypasses RLS.

-- Seed the known sources.
insert into public.sources (type, name, priority) values
  ('dooray', 'Dooray', 10),
  ('kaist_public', 'KAIST 공지', 20),
  ('manual', 'Manual', 5),
  ('portal', 'KAIST Portal', 30)
on conflict (type, name) do nothing;
