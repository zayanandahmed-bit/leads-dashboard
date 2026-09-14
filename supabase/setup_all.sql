-- Signal Board — full Supabase setup, run once.
-- Creates every table the dashboard needs for cross-device sync:
-- lead pipeline status, call history, and clients. Safe to re-run —
-- every statement is "if not exists", so running this again later
-- (e.g. after adding a table) does nothing to what's already there.

-- ---------- 1. Lead pipeline status (leads tab) ----------
create table if not exists lead_status (
  id         text primary key,
  status     text not null default 'new',
  note       text not null default '',
  updated_at timestamptz not null default now()
);

alter table lead_status enable row level security;

drop policy if exists "anon can read lead_status" on lead_status;
create policy "anon can read lead_status" on lead_status for select using (true);

drop policy if exists "anon can upsert lead_status" on lead_status;
create policy "anon can upsert lead_status" on lead_status for insert with check (true);

drop policy if exists "anon can update lead_status" on lead_status;
create policy "anon can update lead_status" on lead_status for update using (true);

-- ---------- 2. Call history (Call system tab) ----------
create table if not exists call_log (
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

create index if not exists call_log_started_at on call_log (started_at desc);
create index if not exists call_log_lead_id on call_log (lead_id);

alter table call_log enable row level security;

drop policy if exists "anon can read call_log" on call_log;
create policy "anon can read call_log" on call_log for select using (true);

drop policy if exists "anon can insert call_log" on call_log;
create policy "anon can insert call_log" on call_log for insert with check (true);

drop policy if exists "anon can delete call_log" on call_log;
create policy "anon can delete call_log" on call_log for delete using (true);

-- ---------- 3. Clients (Clients tab) ----------
create table if not exists clients (
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

create index if not exists clients_status on clients (status);

alter table clients enable row level security;

drop policy if exists "anon can read clients" on clients;
create policy "anon can read clients" on clients for select using (true);

drop policy if exists "anon can insert clients" on clients;
create policy "anon can insert clients" on clients for insert with check (true);

drop policy if exists "anon can update clients" on clients;
create policy "anon can update clients" on clients for update using (true);

drop policy if exists "anon can delete clients" on clients;
create policy "anon can delete clients" on clients for delete using (true);

-- Done — three tables: lead_status (probably already existed), call_log, clients.
select 'setup complete' as result;
