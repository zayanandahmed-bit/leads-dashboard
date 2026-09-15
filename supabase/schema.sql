-- Signal Board pipeline sync: tracks which lead is at what stage, and any
-- notes, so status persists across browsers/devices instead of living only
-- in one person's localStorage. This does NOT store the scraped lead data
-- itself (name/phone/email) — that stays baked into the published page.
-- id = the same lead id the dashboard already uses (phone number, or a
-- "site:<domain>" key when no phone was found).
--
-- Table name is prefixed signalboard_ because this Supabase project is
-- shared with other apps (it already has app_logins, crm_clients, etc.) —
-- a short generic name here risks colliding with one of theirs.

create table if not exists signalboard_lead_status (
  id         text primary key,
  status     text not null default 'new',
  note       text not null default '',
  updated_at timestamptz not null default now()
);

alter table signalboard_lead_status enable row level security;

-- This is a single-user internal tool with no login system, so the anon
-- key (safe to embed in public client-side code) is allowed to read and
-- write freely. It can only touch pipeline status/notes here — never the
-- lead data itself, since that isn't in this table at all.
create policy "anon can read signalboard_lead_status"
  on signalboard_lead_status for select
  using (true);

create policy "anon can upsert signalboard_lead_status"
  on signalboard_lead_status for insert
  with check (true);

create policy "anon can update signalboard_lead_status"
  on signalboard_lead_status for update
  using (true);
