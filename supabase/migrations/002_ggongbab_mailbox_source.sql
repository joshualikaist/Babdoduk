-- Adds the `dooray_mailbox` source type for mailbox backfill.
--
-- Why a separate type: `dooray` means "a task the Dooray auto-classification rule
-- created in the collection project". `dooray_mailbox` means "a message taken from
-- the user's own mailbox export". Same pipeline, different provenance and different
-- privacy footprint, so they must stay distinguishable in `sources` and in the
-- public `sources[].type`.
--
-- Apply after 001. Safe to re-run.

alter table public.sources drop constraint if exists sources_type_check;
alter table public.sources
  add constraint sources_type_check
  check (type in ('dooray', 'dooray_mailbox', 'kaist_public', 'manual', 'portal'));

insert into public.sources (type, name, priority) values
  ('dooray_mailbox', 'Dooray 메일함', 15)
on conflict (type, name) do nothing;
