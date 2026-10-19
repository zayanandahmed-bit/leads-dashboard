/*
 * POST /token  { passcode }  ->  { token, identity, callerId, allowedPrefixes, ttl }
 *
 * Mints a short-lived Twilio Voice access token for the Signal Board's
 * browser dialer. This endpoint has to be publicly reachable (the dashboard
 * is a static page), so it is the one thing standing between the internet
 * and your Twilio balance: without the passcode check anyone who found the
 * URL could mint a token and place calls on your account.
 *
 * Environment (set in .env locally, or Functions > Environment Variables):
 *   API_KEY, API_SECRET   Twilio API key pair (Console > Account > API keys)
 *   TWIML_APP_SID         TwiML App whose Voice URL points at /voice
 *   CALLER_ID             Your Twilio number in E.164, e.g. +442071234567
 *   CALL_PASSCODE         Long random string you type into the dashboard
 *   ALLOWED_ORIGINS       Comma-separated origins allowed to call this,
 *                         e.g. https://zayanandahmed-bit.github.io
 *   ALLOWED_PREFIXES      Comma-separated dialable prefixes (default +44)
 *   AGENTS                Optional. Names of everyone who takes calls, e.g.
 *                         zayan,ahmed. Each signs in under their own name and
 *                         incoming calls ring all of them. Unset = one shared login.
 * ACCOUNT_SID is provided by the Functions runtime automatically.
 */
const crypto = require("crypto");

// Each person gets their own identity ("sb_" + their name) so several people
// can be signed in at once and incoming calls can ring all of them. With
// AGENTS unset, everyone shares the single identity "sb_caller", which is the
// original one-person behaviour.
const IDENTITY_PREFIX = "sb_";

function slug(name) {
  return String(name || "").toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 20);
}
const TTL_SECONDS = 3600;

function list(value, fallback) {
  return String(value || fallback)
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

// Constant-time comparison, so response timing can't be used to guess the
// passcode one character at a time.
function passcodeMatches(given, expected) {
  if (typeof given !== "string" || typeof expected !== "string" || !expected) return false;
  const a = crypto.createHash("sha256").update(given).digest();
  const b = crypto.createHash("sha256").update(expected).digest();
  return crypto.timingSafeEqual(a, b);
}

exports.handler = function (context, event, callback) {
  const response = new Twilio.Response();
  const origin = (event.request && event.request.headers && event.request.headers.origin) || "";
  const allowedOrigins = list(context.ALLOWED_ORIGINS, "");

  // Only echo back an origin we trust — never "*" on an endpoint that
  // hands out calling credentials.
  if (allowedOrigins.includes(origin)) {
    response.appendHeader("Access-Control-Allow-Origin", origin);
    response.appendHeader("Vary", "Origin");
  }
  response.appendHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  response.appendHeader("Access-Control-Allow-Headers", "Content-Type");
  response.appendHeader("Content-Type", "application/json");
  response.appendHeader("Cache-Control", "no-store");

  const fail = (status, message) => {
    response.setStatusCode(status);
    response.setBody({ error: message });
    return callback(null, response);
  };

  if (!allowedOrigins.includes(origin)) {
    return fail(403, "Origin not allowed. Add it to ALLOWED_ORIGINS.");
  }

  const missing = ["API_KEY", "API_SECRET", "TWIML_APP_SID", "CALLER_ID", "CALL_PASSCODE"]
    .filter((k) => !context[k]);
  if (missing.length) {
    return fail(500, "Backend not configured — missing " + missing.join(", "));
  }

  if (!passcodeMatches(event.passcode, context.CALL_PASSCODE)) {
    return fail(401, "Wrong passcode.");
  }

  const agents = list(context.AGENTS, "").map(slug).filter(Boolean);
  let identity = IDENTITY_PREFIX + "caller";
  if (agents.length) {
    const who = slug(event.name);
    if (!agents.includes(who)) {
      return fail(403, "\"" + (String(event.name || "").trim() || "(no name)") +
        "\" isn't on the list of people who can take calls. Put your name in Settings, and add it to AGENTS on the backend.");
    }
    identity = IDENTITY_PREFIX + who;
  }

  const AccessToken = Twilio.jwt.AccessToken;
  const token = new AccessToken(context.ACCOUNT_SID, context.API_KEY, context.API_SECRET, {
    identity: identity,
    ttl: TTL_SECONDS,
  });
  token.addGrant(new AccessToken.VoiceGrant({
    outgoingApplicationSid: context.TWIML_APP_SID,
    incomingAllow: true, // lets calls to your Twilio number ring this browser (see /incoming)
  }));

  response.setBody({
    token: token.toJwt(),
    identity: identity,
    callerId: context.CALLER_ID,
    allowedPrefixes: list(context.ALLOWED_PREFIXES, "+44"),
    // Who records: "twilio", "browser" (the dashboard does) or "none". Sent
    // from here so the server's RECORD_CALLS stays the one place to decide.
    recording: (function () {
      const m = String(context.RECORD_CALLS || "true").toLowerCase();
      return m === "browser" ? "browser" : m === "false" ? "none" : "twilio";
    })(),
    ttl: TTL_SECONDS,
  });
  return callback(null, response);
};
