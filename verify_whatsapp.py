"""
Verify which numbers are actually registered on WhatsApp, via Evolution API.

This replaces guesswork ("a mobile was on their website") with a real answer.
Evolution's whatsappNumbers endpoint asks WhatsApp directly whether a number
exists — no message is sent, nothing is delivered to the business.

Credentials come from the environment or a local .env file — never hardcode
them and never commit them:

    EVOLUTION_API_URL=http://localhost:8080
    EVOLUTION_API_KEY=your-key
    EVOLUTION_INSTANCE=your-instance-name

Run:  python verify_whatsapp.py
Out:  wa_verified.json  -> { "447...": true|false }

Rate limiting matters more than speed here. Existence checks are far cheaper
than messages, but hammering any WhatsApp automation is what gets an account
flagged. Defaults are deliberately gentle; raise them at your own risk.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BATCH_SIZE = int(os.environ.get("EVO_BATCH_SIZE", "20"))
BATCH_PAUSE = float(os.environ.get("EVO_BATCH_PAUSE", "3.0"))
OUT_PATH = "wa_verified.json"


def load_env(path=".env"):
    """Minimal .env reader so credentials never have to be pasted anywhere."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def config():
    load_env()
    url = os.environ.get("EVOLUTION_API_URL", "").rstrip("/")
    key = os.environ.get("EVOLUTION_API_KEY", "")
    inst = os.environ.get("EVOLUTION_INSTANCE", "")
    missing = [n for n, v in
               (("EVOLUTION_API_URL", url), ("EVOLUTION_API_KEY", key),
                ("EVOLUTION_INSTANCE", inst)) if not v]
    if missing:
        sys.exit(
            "Missing: " + ", ".join(missing) +
            "\n\nCreate a .env file next to this script containing:\n"
            "  EVOLUTION_API_URL=http://localhost:8080\n"
            "  EVOLUTION_API_KEY=your-key\n"
            "  EVOLUTION_INSTANCE=your-instance-name\n"
            "\n(.env is gitignored — your key stays on your machine.)"
        )
    return url, key, inst


def check_batch(url, key, inst, numbers):
    """Ask Evolution which of these numbers exist on WhatsApp."""
    # Instance names may contain spaces or punctuation ("A.P.I.S for Ali"),
    # so they must be escaped before going into the path.
    endpoint = f"{url}/chat/whatsappNumbers/{urllib.parse.quote(inst, safe='')}"
    body = json.dumps({"numbers": numbers}).encode()
    req = urllib.request.Request(
        endpoint, data=body, method="POST",
        headers={"Content-Type": "application/json", "apikey": key},
    )
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def parse(payload, sent):
    """Evolution has shipped a few response shapes; handle them all."""
    out = {}
    rows = payload if isinstance(payload, list) else (
        payload.get("data") or payload.get("result") or []
    )
    for row in rows:
        if not isinstance(row, dict):
            continue
        num = str(row.get("number") or row.get("jid") or "").split("@")[0]
        num = "".join(ch for ch in num if ch.isdigit())
        exists = row.get("exists")
        if exists is None:
            exists = bool(row.get("jid"))
        if num:
            out[num] = bool(exists)
    # Anything the API didn't mention came back as not-on-WhatsApp.
    for n in sent:
        out.setdefault(n, False)
    return out


def main(leads_path="/tmp/leads.json"):
    url, key, inst = config()

    leads = json.load(open(leads_path, encoding="utf-8"))

    # prep_leads.py already builds the country-correct candidate list per
    # lead (its own site's number, then whatever Maps listed) and stores the
    # best one in `wa` — including landlines, since WhatsApp Business can be
    # registered to one. Trust that rather than re-deriving from raw phone
    # numbers here, which would need the same per-country cc logic again.
    numbers = sorted({l["wa"] for l in leads if l.get("wa")})

    results = {}
    if os.path.exists(OUT_PATH):
        try:
            results = json.load(open(OUT_PATH, encoding="utf-8"))
            print(f"resuming — {len(results)} already verified")
        except json.JSONDecodeError:
            pass

    todo = [n for n in numbers if n not in results]
    if not todo:
        print("nothing new to verify")
        return

    print(f"verifying {len(todo)} numbers via Evolution "
          f"({BATCH_SIZE} per batch, {BATCH_PAUSE}s pause)…\n")

    for i in range(0, len(todo), BATCH_SIZE):
        batch = todo[i:i + BATCH_SIZE]
        try:
            payload = check_batch(url, key, inst, batch)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:300]
            print(f"  HTTP {e.code} on batch {i // BATCH_SIZE + 1}: {detail}")
            if e.code in (401, 403):
                sys.exit("Auth rejected — check EVOLUTION_API_KEY.")
            if e.code == 404:
                sys.exit(f"Instance '{inst}' not found — check EVOLUTION_INSTANCE.")
            continue
        except (urllib.error.URLError, OSError) as e:
            sys.exit(f"Cannot reach {url} — is Evolution running? ({e})")

        results.update(parse(payload, batch))

        tmp = OUT_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(results, f)
        os.replace(tmp, OUT_PATH)

        live = sum(1 for v in results.values() if v)
        print(f"  {min(i + BATCH_SIZE, len(todo))}/{len(todo)} checked — "
              f"{live} on WhatsApp", flush=True)

        if i + BATCH_SIZE < len(todo):
            time.sleep(BATCH_PAUSE)

    live = sum(1 for v in results.values() if v)
    print(f"\n{live} of {len(results)} numbers are on WhatsApp")
    print(f"written to {OUT_PATH} — rebuild with: python build_dashboard.py uk_leads_master.csv")


if __name__ == "__main__":
    a = sys.argv[1:]
    country_key = "uk"
    for flag in ("--uk", "--uae", "--usa"):
        if flag in a:
            country_key = flag[2:]
            a.remove(flag)
    default_leads = f"/tmp/leads_{country_key}.json"
    main(a[0] if a else default_leads)
