/*
 * POST /announce  (Twilio webhook, fetched by /voice via <Number url=...>)
 *
 * Only used when RECORDING_NOTICE is set. Plays that wording to the person you
 * called, right after they pick up and before you are connected. Left unset,
 * /voice never calls this and nothing is played: the caller says it themselves.
 *
 * ".protected": only Twilio itself can call this.
 */
exports.handler = function (context, event, callback) {
  const twiml = new Twilio.twiml.VoiceResponse();
  if (context.RECORDING_NOTICE) twiml.say({ voice: "Polly.Amy" }, context.RECORDING_NOTICE);
  // No <Hangup>: when this document ends, Twilio bridges the call to you.
  return callback(null, twiml);
};
