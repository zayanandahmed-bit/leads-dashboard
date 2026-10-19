/*
 * POST /recording  { passcode, callSid }  ->  { audio (base64), type, durationSec }
 *
 * Fetches the recording of one call for the dashboard's Play button.
 *
 * Recordings are not public: Twilio only serves the audio to someone with the
 * account's credentials, and those must never reach the dashboard (a public
 * page). So the dashboard sends the passcode instead, and this function does
 * the authenticated fetch on its behalf, exactly as /token guards token minting.
 *
 * Limit: a Twilio Function can return at most 4 MB, and base64 adds a third.
 * A mono mp3 recording of roughly 8 minutes fits. Longer ones come back as
 * 413 and have to be played from Twilio Console > Monitor > Recordings.
 *
 * Environment: API_KEY, API_SECRET, CALL_PASSCODE, ALLOWED_ORIGINS (as /token).
 * ACCOUNT_SID is provided by the Functions runtime.
 */
const crypto = require("crypto");

const MAX_RAW_BYTES = 2900000; // 2.9 MB raw -> ~3.87 MB once base64-encoded

function list(value) {
  return String(value || "").split(",").map((s) => s.trim()).filter(Boolean);
}

function passcodeMatches(given, expected) {
  if (typeof given !== "string" || typeof expected !== "string" || !expected) return false;
  const a = crypto.createHash("sha256").update(given).digest();
  const b = crypto.createHash("sha256").update(expected).digest();
  return crypto.timingSafeEqual(a, b);
}

exports.handler = async function (context, event, callback) {
  const response = new Twilio.Response();
  const origin = (event.request && event.request.headers && event.request.headers.origin) || "";
  const allowedOrigins = list(context.ALLOWED_ORIGINS);

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

  if (!allowedOrigins.includes(origin)) return fail(403, "Origin not allowed.");
  if (!passcodeMatches(event.passcode, context.CALL_PASSCODE)) return fail(401, "Wrong passcode.");

  // A CallSid is "CA" + 32 hex characters. Checking the shape means this can
  // never be steered into fetching anything other than a recording lookup.
  const callSid = String(event.callSid || "");
  if (!/^CA[0-9a-f]{32}$/i.test(callSid)) return fail(400, "That isn't a call id.");

  try {
    const client = require("twilio")(context.API_KEY, context.API_SECRET, {
      accountSid: context.ACCOUNT_SID,
    });
    const found = await client.recordings.list({ callSid, limit: 1 });
    if (!found.length) {
      return fail(404, "No recording for that call yet. It can take a minute after the call ends, and calls nobody answered have none.");
    }
    const rec = found[0];
    if (rec.status !== "completed") return fail(409, "The recording is still being processed. Try again in a minute.");

    const mediaUrl = "https://api.twilio.com/2010-04-01/Accounts/" + context.ACCOUNT_SID +
      "/Recordings/" + rec.sid + ".mp3";
    const media = await fetch(mediaUrl, {
      headers: {
        Authorization: "Basic " + Buffer.from(context.API_KEY + ":" + context.API_SECRET).toString("base64"),
      },
    });
    if (!media.ok) return fail(502, "Twilio wouldn't hand over the recording (" + media.status + ").");

    const bytes = Buffer.from(await media.arrayBuffer());
    if (bytes.length > MAX_RAW_BYTES) {
      return fail(413, "Too long to play here. Open it in Twilio Console > Monitor > Recordings.");
    }

    response.setBody({
      audio: bytes.toString("base64"),
      type: "audio/mpeg",
      durationSec: Number(rec.duration) || null,
    });
    return callback(null, response);
  } catch (err) {
    return fail(500, "Couldn't fetch the recording.");
  }
};
