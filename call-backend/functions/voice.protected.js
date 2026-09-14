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
 */
const IDENTITY = "client:signalboard-caller";

// UK premium-rate and personal-numbering ranges that cost the CALLER a lot
// and are a classic fraud target. Blocked even though they start with +44.
const BLOCKED_PREFIXES = ["+449", "+4470", "+44871", "+44872", "+44873"];

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

  if (event.From !== IDENTITY) {
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
  if (BLOCKED_PREFIXES.some((p) => to.startsWith(p))) {
    return refuse("Premium rate numbers are blocked.");
  }

  const dial = twiml.dial({
    callerId: context.CALLER_ID,
    // Keep the browser in "ringing" until the other side actually picks up,
    // so the dashboard's talk-time only counts real conversation.
    answerOnBridge: true,
    timeout: 30,
    timeLimit: 1800, // hard 30-minute cap so a forgotten call can't run up a bill
  });
  dial.number(to);
  return callback(null, twiml);
};
