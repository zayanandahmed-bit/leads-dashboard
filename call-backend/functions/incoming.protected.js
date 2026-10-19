/*
 * POST /incoming  (Twilio webhook, set as "A call comes in" on your Twilio number)
 *
 * When a lead rings your Twilio number back, this rings your dashboard login.
 * Every browser signed in with it (say, two of them) rings at once, and the
 * first to answer gets the call while the other stops. A browser already on a
 * call quietly ignores a second call, so it keeps ringing the other browser.
 * (If AGENTS is set, each named login rings instead.)
 *
 * If nobody picks up within 25 seconds, or no dashboard is open, the call
 * ends (the caller isn't charged) and /incoming-done records it as missed.
 *
 * ".protected": only Twilio itself can call this.
 *
 * Recording follows RECORD_CALLS as for outgoing calls: "true"/"twilio" has
 * Twilio record from the moment someone answers; "browser" leaves it to the
 * dashboard; "false" records nothing.
 */
function slug(name) {
  return String(name || "").toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 20);
}

exports.handler = function (context, event, callback) {
  const twiml = new Twilio.twiml.VoiceResponse();
  const mode = String(context.RECORD_CALLS || "true").toLowerCase();
  const recording = mode === "true" || mode === "twilio";

  const dial = twiml.dial({
    answerOnBridge: true,
    timeout: 25,
    timeLimit: 1800,
    // Twilio asks this when the dial ends, answered or not.
    action: "https://" + context.DOMAIN_NAME + "/incoming-done",
    method: "POST",
    ...(recording ? { record: "record-from-answer" } : {}),
  });

  const agents = String(context.AGENTS || "").split(",").map(slug).filter(Boolean);
  (agents.length ? agents : ["caller"]).forEach((a) => dial.client("sb_" + a));
  return callback(null, twiml);
};
