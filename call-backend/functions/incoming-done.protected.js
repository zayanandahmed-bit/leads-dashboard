/*
 * POST /incoming-done  (Twilio webhook: the <Dial> in /incoming ends)
 *
 * If nobody answered, writes a "missed call" row into the shared call log so
 * it shows on every device's Inbound tab. Answered calls are logged by the
 * person who took them (with the same id, "in-<CallSid>", so they never
 * double up), so this does nothing for those.
 *
 * Needs SUPABASE_URL and SUPABASE_ANON_KEY in the environment, the same two
 * public values the dashboard uses. Without them, missed calls simply aren't
 * logged; nothing else is affected.
 *
 * ".protected": only Twilio itself can call this.
 */
exports.handler = async function (context, event, callback) {
  const twiml = new Twilio.twiml.VoiceResponse();
  const answered = event.DialCallStatus === "completed";

  if (!answered && context.SUPABASE_URL && context.SUPABASE_ANON_KEY && /^CA[0-9a-f]{32}$/i.test(String(event.CallSid || ""))) {
    try {
      await fetch(context.SUPABASE_URL + "/rest/v1/signalboard_call_log", {
        method: "POST",
        headers: {
          apikey: context.SUPABASE_ANON_KEY,
          Authorization: "Bearer " + context.SUPABASE_ANON_KEY,
          "Content-Type": "application/json",
          // ignore-duplicates: Twilio can retry a webhook, and a retry must not double-log.
          Prefer: "resolution=ignore-duplicates,return=minimal",
        },
        body: JSON.stringify([{
          id: "in-" + event.CallSid,
          lead_id: null,
          line: "manual",
          manual_number: String(event.From || "").replace(/[^\d+]/g, "") || null,
          started_at: new Date().toISOString(),
          ring_sec: Number(event.DialCallDuration) || 0,
          talk_sec: 0,
          outcome: "no_answer",
          note: "Missed inbound call",
          caller: "",
          direction: "in",
        }]),
      });
    } catch (err) {
      // A failed log write must never break the call flow.
    }
  }
  return callback(null, twiml);
};
