-- Clients tab: your paying, monthly clients — separate from leads and
-- call_log. This DOES hold real client data (name, contact details, what
-- they pay), unlike lead_status/call_log which only reference the scraped
-- lead data by id. That's intentional: a client isn't in the scraped
-- dataset, so there's nowhere else for their details to live.
--
-- One row per client. Payments are kept as a JSON array on the row itself
-- rather than a second table — a solo operator logs a handful of payments
-- a month per client, so there's no real list to paginate, and one row per
-- client keeps the sync logic identical to lead_status's upsert pattern.
--
-- Run once in the Supabase SQL editor. Until then, the dashboard keeps
-- clients on the device they were added on.

create table if not exists clients (
  id           text primary key,          -- generated in the browser
  name         text not null,
  phone        text not null default '',
  whatsapp     text not null default '',
  email        text not null default '',
  monthly_fee  numeric not null default 0,
  currency     text not null default 'USD',
  status       text not null default 'active',   -- 'active' | 'paused' | 'cancelled'
  started_at   timestamptz not null default now(),
  notes        text not null default '',
  payments     jsonb not null default '[]',       -- [{id, date, amount, method, note}]
  caller       text not null default '',           -- who added/last touched it
  updated_at   timestamptz not null default now(),
  created_at   timestamptz not null default now()
);

create index if not exists clients_status on clients (status);

alter table clients enable row level security;

-- Same reasoning as lead_status: single-user internal tool, no login
-- system, so the anon key (safe to embed in public client-side code) can
-- read and write freely. Update is allowed here — unlike call_log, a
-- client's fee or contact details legitimately change over time and
-- should overwrite in place, not pile up as new rows.
create policy "anon can read clients"
  on clients for select
  using (true);

create policy "anon can insert clients"
  on clients for insert
  with check (true);

create policy "anon can update clients"
  on clients for update
  using (true);

create policy "anon can delete clients"
  on clients for delete
  using (true);
