# Signal Board — Call system backend (Twilio)

Two tiny Twilio Functions that let the dashboard's **Call system** tab place
real phone calls from your browser:

| Function | What it does |
|---|---|
| `/token` | Checks your passcode, then hands the browser a 1-hour, dial-out-only Twilio token |
| `/voice` | Twilio asks this what to do with each call. It only dials allowed country prefixes (UK by default), blocks premium-rate numbers, and refuses anything not placed from the dashboard |

Your Twilio secrets live only in Twilio's environment variables — never in the
dashboard, which is a public page.

You don't need this to try the Call system: turn on **Demo mode** in its
settings and every button works with simulated calls.

---

## One-time setup (about 30 minutes, plus UK number approval time)

### 1. Twilio account
Sign up at twilio.com and add credit. You enter your own details and payment —
nobody else should do this for you.

### 2. Buy a UK number
Console → Phone Numbers → Buy a number → United Kingdom, **Voice** capable.

UK numbers need a **Regulatory Bundle** (your name/business, address, and ID)
before Twilio will activate them. Approval can take a few days — start this first.

### 3. Create an API key
Console → Account → API keys & tokens → Create API key → **Standard**.
Save the SID (`SK…`) and the secret — the secret is shown once.

### 4. Deploy the functions
Needs Node 20 or 22.

```bash
cd call-backend
cp .env.example .env        # then fill it in — see comments inside
npm install
npm run deploy
```

The output ends with your function URLs, e.g.
`https://signalboard-calls-1234-dev.twil.io/token`. Note the base
(`https://signalboard-calls-1234-dev.twil.io`).

Generate the passcode with `openssl rand -base64 24`.

### 5. Create the TwiML App
Console → Voice → TwiML Apps → Create:
- **Voice Request URL**: `https://<your base>/voice` (method POST)

Copy its SID (`AP…`) into `TWIML_APP_SID` in `.env`, then run `npm run deploy` again.

### 6. Connect the dashboard
Open the dashboard → **Call system** tab → **Settings**:
- Backend URL: `https://<your base>`
- Passcode: the `CALL_PASSCODE` you set
- Turn Demo mode **off** → **Connect**

The passcode is saved only in that browser.

---

## Costs (check twilio.com/voice/pricing/gb — rates change)
- UK local number: roughly $1–2 / month
- Browser → UK landline: roughly 1–2¢ / minute; UK mobiles cost more
- You pay for ringing time on answered calls; unanswered calls that hit
  `timeout` (30 s) are not connected

## Safety limits built in
- Wrong passcode, or a request from a site not in `ALLOWED_ORIGINS` → no token
- Only numbers starting with `ALLOWED_PREFIXES` can be dialled (default `+44`)
- UK premium-rate (`09…`), personal-numbering (`070…`) and `0871–0873` are always blocked
- Every call is cut off after 30 minutes
- Tokens can't receive calls — dial-out only

If the passcode ever leaks, change `CALL_PASSCODE` and redeploy.

## UK calling rules
Cold-calling UK businesses is legal, but under PECR you must not call numbers
registered on the **Corporate TPS (CTPS)** unless they've agreed to hear from
you, you must show a real caller ID you can be called back on, and you must
stop calling anyone who asks. Use the dashboard's **Do not call** outcome for
the last one — it removes the lead from the queue for good.
