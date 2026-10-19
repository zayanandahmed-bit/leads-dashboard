/*
 * POST /voice  (Twilio webhook — the TwiML App's Voice URL)
 *
 * When the browser dialer places a call, Twilio asks this function what to
 * do with it. ".protected" makes the Functions runtime reject any request
 * without a valid X-Twilio-Signature, so only Twilio itself can hit it.
 *
 * Even with a valid token, this is the last line of defence against toll
 * fraud, so it re-checks everything instead of trusting the browser:
 *   - the call must come from the dashboard's own client identity
 *   - the destination must be a well-formed E.164 number
 *   - the destination must start with an allowed prefix (default +44 only),
 *     which blocks premium-rate and international-revenue-share scams
 *
 * Recording: unless RECORD_CALLS=false the call is recorded from the moment
 * the other person answers: by Twilio in the default mode, or by the dashboard
 * in "browser" mode (see /token). Telling them is the caller's job. The
 * dashboard shows a reminder during every recorded call. If RECORDING_NOTICE
 * is set, a recorded voice also says it (see /announce), before you connect.
 */
const IDENTITY_PREFIX = "client:sb_";   // every dashboard login is "sb_<name>"

// UK ranges that cost the CALLER a lot and are classic fraud targets, blocked
// even though they start with +44: 09 premium rate, 070 personal numbering,
// 076 pagers, 084/087 service-charge numbers.
const BLOCKED_PREFIXES = ["+449", "+4470", "+4476", "+4484", "+4487"];
// Isle of Man mobiles sit inside the 076 range and are ordinary mobiles.
const BLOCK_EXCEPTIONS = ["+447624"];

function list(value, fallback) {
  return String(value || fallback)
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

exports.handler = function (context, event, callback) {
  const twiml = new Twilio.twiml.VoiceResponse();
  const refuse = (spoken) => {
    twiml.say({ voice: "Polly.Amy" }, spoken);
    twiml.hangup();
    return callback(null, twiml);
  };

  if (!String(event.From || "").startsWith(IDENTITY_PREFIX)) {
    return refuse("This call was not placed from the Signal Board dialer.");
  }

  const to = String(event.To || "").replace(/[^\d+]/g, "");
  if (!/^\+[1-9]\d{7,14}$/.test(to)) {
    return refuse("That number is not in international format.");
  }

  const allowed = list(context.ALLOWED_PREFIXES, "+44");
  if (!allowed.some((p) => to.startsWith(p))) {
    return refuse("Calls to that country are not enabled.");
  }
  if (BLOCKED_PREFIXES.some((p) => to.startsWith(p)) && !BLOCK_EXCEPTIONS.some((p) => to.startsWith(p))) {
    return refuse("Premium rate numbers are blocked.");
  }
  // A UK number is +44 then 9 or 10 digits. Refuse anything else up front
  // rather than paying for a call attempt that can't connect.
  if (to.startsWith("+44") && !/^\+44\d{9,10}$/.test(to)) {
    return refuse("That UK number has the wrong number of digits.");
  }

  // RECORD_CALLS: "true"/"twilio" = Twilio records (default), "browser" = the
  // dashboard records on its own side and Twilio stores nothing, "false" = no
  // recording. No automated notice is played unless RECORDING_NOTICE is set:
  // the caller says it themselves, and the dashboard reminds them to.
  const mode = String(context.RECORD_CALLS || "true").toLowerCase();
  const notice = mode !== "false" && !!String(context.RECORDING_NOTICE || "").trim();
  const recording = mode === "true" || mode === "twilio";

  const dial = twiml.dial({
    callerId: context.CALLER_ID,
    // Keep the browser in "ringing" until the other side actually picks up,
    // so the dashboard's talk-time only counts real conversation.
    answerOnBridge: true,
    timeout: 30,
    timeLimit: 1800, // hard 30-minute cap so a forgotten call can't run up a bill
    // Mono, from answer: ringing time isn't recorded or billed as recording,
    // and a mono mp3 is small enough for /recording to hand to the dashboard
    // (Twilio Functions cap a response at 4 MB; two-channel would halve the
    // length that fits).
    ...(recording ? { record: "record-from-answer" } : {}),
  });
  if (notice) {
    // `url` runs on the called person's leg right after they answer and
    // before they are connected to you, which is where a notice has to play.
    dial.number({ url: "https://" + context.DOMAIN_NAME + "/announce", method: "POST" }, to);
  } else {
    dial.number(to);
  }
  return callback(null, twiml);
};
