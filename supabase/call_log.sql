-- Call System log: one row per call placed from the Signal Board's
-- "Call system" tab, so call history and callbacks are shared across
-- devices and callers instead of living in one browser.
--
-- Same principle as signalboard_lead_status: this does NOT copy the
-- scraped lead data (name/phone/email) into the database. A lead call
-- stores the lead id and which line was dialled; the dashboard looks the
-- rest up itself. Only a manually typed number (no lead) is stored as a
-- number.
--
-- Table name is prefixed signalboard_ because this Supabase project is
-- shared with other apps — a short generic name here risks colliding.
--
-- Run once in the Supabase SQL editor. Until then, the dashboard keeps the
-- call log on the device it was made on.

create table if not exists signalboard_call_log (
  id           text primary key,          -- generated in the browser, so retries can't duplicate
  lead_id      text,                      -- null for a manually dialled number
  line         text not null default 'main',   -- 'main' | 'mobile' | 'manual'
  manual_number text,                     -- only set when line = 'manual'
  started_at   timestamptz not null,
  ring_sec     integer not null default 0,
  talk_sec     integer not null default 0,
  outcome      text not null,
  note         text not null default '',
  callback_at  timestamptz,
  caller       text not null default '',
  created_at   timestamptz not null default now()
);

create index if not exists signalboard_call_log_started_at on signalboard_call_log (started_at desc);
create index if not exists signalboard_call_log_lead_id on signalboard_call_log (lead_id);

alter table signalboard_call_log enable row level security;

-- Read, insert and delete — deliberately no update policy, so a call record
-- can't be quietly rewritten after the fact. Delete exists so a call logged
-- by mistake can be removed from the dashboard (Undo / the × on a row).
create policy "anon can read signalboard_call_log"
  on signalboard_call_log for select
  using (true);

create policy "anon can insert signalboard_call_log"
  on signalboard_call_log for insert
  with check (true);

create policy "anon can delete signalboard_call_log"
  on signalboard_call_log for delete
  using (true);
