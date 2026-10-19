-- Private bucket for call recordings. Run once in the Supabase SQL editor.
--
-- Recordings are audio of other people, so the bucket is private and has NO
-- policies: the dashboard's public key can neither read nor write it. Only the
-- call backend can, using the project's service key, and it hands the dashboard
-- one-use links after checking your passcode (call-backend/functions/recording-url.js).

insert into storage.buckets (id, name, public)
values ('signalboard-recordings', 'signalboard-recordings', false)
on conflict (id) do nothing;

-- Which recording belongs to which call, and whether the call was inbound.
alter table signalboard_call_log add column if not exists rec_id text;
alter table signalboard_call_log add column if not exists direction text not null default 'out';

select 'recordings ready' as result;
