-- Clients tab: your paying, monthly clients — separate from leads and
-- call_log. This DOES hold real client data (name, contact details, what
-- they pay), unlike signalboard_lead_status/signalboard_call_log which
-- only reference the scraped lead data by id. That's intentional: a
-- client isn't in the scraped dataset, so there's nowhere else for their
-- details to live.
--
-- One row per client. Payments are kept as a JSON array on the row itself
-- rather than a second table — a solo operator logs a handful of payments
-- a month per client, so there's no real list to paginate, and one row per
-- client keeps the sync logic identical to signalboard_lead_status's
-- upsert pattern.
--
-- Table name is prefixed signalboard_ because this Supabase project is
-- shared with other apps (it already has its own crm_clients table) — a
-- plain "clients" here would collide with that.
--
-- Run once in the Supabase SQL editor. Until then, the dashboard keeps
-- clients on the device they were added on.

create table if not exists signalboard_clients (
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
  payments     jsonb not null default '[]',       -- [{id, date, amount, type, method, note}]
  caller       text not null default '',           -- who added/last touched it
  updated_at   timestamptz not null default now(),
  created_at   timestamptz not null default now()
);

create index if not exists signalboard_clients_status on signalboard_clients (status);

alter table signalboard_clients enable row level security;

-- Same reasoning as signalboard_lead_status: single-user internal tool, no
-- login system, so the anon key (safe to embed in public client-side code)
-- can read and write freely. Update is allowed here — unlike
-- signalboard_call_log, a client's fee or contact details legitimately
-- change over time and should overwrite in place, not pile up as new rows.
create policy "anon can read signalboard_clients"
  on signalboard_clients for select
  using (true);

create policy "anon can insert signalboard_clients"
  on signalboard_clients for insert
  with check (true);

create policy "anon can update signalboard_clients"
  on signalboard_clients for update
  using (true);

create policy "anon can delete signalboard_clients"
  on signalboard_clients for delete
  using (true);
