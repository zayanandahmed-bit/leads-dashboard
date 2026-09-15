-- Signal Board — full Supabase setup, run once.
-- Creates every table the dashboard needs for cross-device sync: lead
-- pipeline status, call history, and clients. Every table is prefixed
-- signalboard_ because this Supabase project is shared with other apps
-- (it already has its own app_logins, crm_clients, etc.) — a short
-- generic name here risks colliding with one of theirs.
--
-- Safe to re-run: every statement is create-if-not-exists or
-- drop-then-create, so running this again later (e.g. after adding a
-- table) does nothing to data that's already there.

-- ---------- 1. Lead pipeline status (leads tab) ----------
create table if not exists signalboard_lead_status (
  id         text primary key,
  status     text not null default 'new',
  note       text not null default '',
  updated_at timestamptz not null default now()
);

alter table signalboard_lead_status enable row level security;

drop policy if exists "anon can read signalboard_lead_status" on signalboard_lead_status;
create policy "anon can read signalboard_lead_status" on signalboard_lead_status for select using (true);

drop policy if exists "anon can upsert signalboard_lead_status" on signalboard_lead_status;
create policy "anon can upsert signalboard_lead_status" on signalboard_lead_status for insert with check (true);

drop policy if exists "anon can update signalboard_lead_status" on signalboard_lead_status;
create policy "anon can update signalboard_lead_status" on signalboard_lead_status for update using (true);

-- Carries over anything already saved under the old, un-prefixed
-- "lead_status" table (from before this rename) — only runs if that old
-- table exists, and never overwrites a row that's already been copied.
do $$
begin
  if exists (select 1 from information_schema.tables where table_schema = 'public' and table_name = 'lead_status') then
    insert into signalboard_lead_status (id, status, note, updated_at)
    select id, status, note, updated_at from lead_status
    on conflict (id) do nothing;
  end if;
end $$;

-- ---------- 2. Call history (Call system tab) ----------
create table if not exists signalboard_call_log (
  id            text primary key,
  lead_id       text,
  line          text not null default 'main',
  manual_number text,
  started_at    timestamptz not null,
  ring_sec      integer not null default 0,
  talk_sec      integer not null default 0,
  outcome       text not null,
  note          text not null default '',
  callback_at   timestamptz,
  caller        text not null default '',
  created_at    timestamptz not null default now()
);

create index if not exists signalboard_call_log_started_at on signalboard_call_log (started_at desc);
create index if not exists signalboard_call_log_lead_id on signalboard_call_log (lead_id);

alter table signalboard_call_log enable row level security;

drop policy if exists "anon can read signalboard_call_log" on signalboard_call_log;
create policy "anon can read signalboard_call_log" on signalboard_call_log for select using (true);

drop policy if exists "anon can insert signalboard_call_log" on signalboard_call_log;
create policy "anon can insert signalboard_call_log" on signalboard_call_log for insert with check (true);

drop policy if exists "anon can delete signalboard_call_log" on signalboard_call_log;
create policy "anon can delete signalboard_call_log" on signalboard_call_log for delete using (true);

-- ---------- 3. Clients (Clients tab) ----------
create table if not exists signalboard_clients (
  id          text primary key,
  name        text not null,
  phone       text not null default '',
  whatsapp    text not null default '',
  email       text not null default '',
  monthly_fee numeric not null default 0,
  currency    text not null default 'USD',
  status      text not null default 'active',
  started_at  timestamptz not null default now(),
  notes       text not null default '',
  payments    jsonb not null default '[]',
  caller      text not null default '',
  updated_at  timestamptz not null default now(),
  created_at  timestamptz not null default now()
);

create index if not exists signalboard_clients_status on signalboard_clients (status);

alter table signalboard_clients enable row level security;

drop policy if exists "anon can read signalboard_clients" on signalboard_clients;
create policy "anon can read signalboard_clients" on signalboard_clients for select using (true);

drop policy if exists "anon can insert signalboard_clients" on signalboard_clients;
create policy "anon can insert signalboard_clients" on signalboard_clients for insert with check (true);

drop policy if exists "anon can update signalboard_clients" on signalboard_clients;
create policy "anon can update signalboard_clients" on signalboard_clients for update using (true);

drop policy if exists "anon can delete signalboard_clients" on signalboard_clients;
create policy "anon can delete signalboard_clients" on signalboard_clients for delete using (true);

-- Done — three tables: signalboard_lead_status, signalboard_call_log, signalboard_clients.
select 'setup complete' as result;
