-- Signal Board pipeline sync: tracks which lead is at what stage, and any
-- notes, so status persists across browsers/devices instead of living only
-- in one person's localStorage. This does NOT store the scraped lead data
-- itself (name/phone/email) — that stays baked into the published page.
-- id = the same lead id the dashboard already uses (phone number, or a
-- "site:<domain>" key when no phone was found).

create table if not exists lead_status (
  id         text primary key,
  status     text not null default 'new',
  note       text not null default '',
  updated_at timestamptz not null default now()
);

alter table lead_status enable row level security;

-- This is a single-user internal tool with no login system, so the anon
-- key (safe to embed in public client-side code) is allowed to read and
-- write freely. It can only touch pipeline status/notes here — never the
-- lead data itself, since that isn't in this table at all.
create policy "anon can read lead_status"
  on lead_status for select
  using (true);

create policy "anon can upsert lead_status"
  on lead_status for insert
  with check (true);

create policy "anon can update lead_status"
  on lead_status for update
  using (true);
