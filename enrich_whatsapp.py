"""
Find each lead's REAL WhatsApp number.

Google Maps lists the reception landline, which is never on WhatsApp. The
number that is on WhatsApp is usually published on the business's own site —
as a wa.me/ link, a click-to-chat widget, or a plain 07xxx mobile.

Writes whatsapp.json: { website: {"wa": "447...", "src": "wa.me|mobile"} }
"""

import concurrent.futures
import gzip
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request

# Hard ceiling on how long any single site may take across all its paths.
SITE_DEADLINE = 25

# How far either side of a number to look for the word "WhatsApp".
CONTEXT_WINDOW = 300

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# wa.me/447..., api.whatsapp.com/send?phone=447..., web.whatsapp.com/send?phone=
WA_LINK_RE = re.compile(
    r"(?:wa\.me/|whatsapp\.com/send\?phone=|whatsapp://send\?phone=)\+?(\d{9,15})",
    re.I,
)

# Per-country mobile matcher (national or +cc form, tolerant of spaces/
# dashes/parens) and the E.164 shape a valid mobile normalises to.
COUNTRY_PATTERNS = {
    "uk": {
        # 07xxx xxxxxx / +447xxx / 447xxx
        "mobile_re": re.compile(r"(?:(?:\+|00)?44[\s\-.()]*|0)7[\s\-.()]*(?:\d[\s\-.()]*){9}"),
        "cc": "44",
        "e164_re": re.compile(r"^447\d{9}$"),
    },
    "uae": {
        # 05x xxx xxxx / +9715x / 9715x — mobile lead digits 50/52/54/55/56/58
        "mobile_re": re.compile(
            r"(?:(?:\+|00)?971[\s\-.()]*|0)5[024568][\s\-.()]*(?:\d[\s\-.()]*){7}"
        ),
        "cc": "971",
        "e164_re": re.compile(r"^9715[024568]\d{7}$"),
    },
    "usa": {
        # (305) 555-0123 / 305-555-0123 / +1 305 555 0123 — no reserved
        # mobile range in NANP, so this just matches any US-shaped number.
        "mobile_re": re.compile(
            r"(?:\+?1[\s\-.]*)?\(?\d{3}\)?[\s\-.]*\d{3}[\s\-.]*\d{4}\b"
        ),
        "cc": "1",
        "e164_re": re.compile(r"^1\d{10}$"),
    },
}

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# Junk that matches the email pattern but isn't a real contact address.
EMAIL_JUNK = re.compile(
    r"\.(png|jpe?g|gif|svg|webp|css|js)$|"
    r"^(example|test|user|name|you|info)@example\.|"
    r"sentry\.io|wixpress\.com|schema\.org|w3\.org",
    re.I,
)

PATHS = ["", "/contact", "/contact-us", "/contact.html", "/book", "/booking"]


def normalise(raw: str, country: dict) -> str | None:
    """Return an E.164 mobile number for this country, or None."""
    n = re.sub(r"[^\d]", "", raw)
    cc = country["cc"]
    if n.startswith("00"):
        n = n[2:]
    if n.startswith("0"):
        n = cc + n[1:]
    if not n.startswith(cc):
        n = cc + n  # a bare national number with no leading 0
    return n if country["e164_re"].match(n) else None


def fetch(url: str, timeout: int = 9) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Encoding": "gzip", "Accept": "text/html"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(900_000)
        if r.headers.get("Content-Encoding") == "gzip":
            try:
                raw = gzip.decompress(raw)
            except OSError:
                pass
        return raw.decode("utf-8", "ignore")


def find_email(html: str) -> str:
    for m in EMAIL_RE.finditer(html):
        addr = m.group(0)
        if not EMAIL_JUNK.search(addr):
            return addr.lower()
    return ""


def scan(site: str, country: dict):
    """Return {"wa": (number, source) or None, "email": str} for a site."""
    base = site if site.startswith("http") else "https://" + site
    base = base.rstrip("/")

    deadline = time.monotonic() + SITE_DEADLINE
    wa_fallback = None
    wa_result = None
    email = ""

    for path in PATHS:
        if time.monotonic() > deadline:
            break  # this site has had its share of the budget
        try:
            html = fetch(base + path)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError,
                ValueError, socket.timeout):
            continue
        except Exception:
            continue

        if not email:
            email = find_email(html)

        # A wa.me link is explicit intent — trust it over a loose number match.
        for m in WA_LINK_RE.finditer(html):
            num = normalise(m.group(1), country)
            if num:
                wa_result = (num, "wa.me")
                break

        if not wa_result:
            # Next best: a mobile printed beside the word "WhatsApp" — almost
            # as strong as a link, since the business is publishing it AS
            # their WhatsApp.
            for m in country["mobile_re"].finditer(html):
                num = normalise(m.group(0), country)
                if not num:
                    continue
                window = html[max(0, m.start() - CONTEXT_WINDOW):
                              m.end() + CONTEXT_WINDOW].lower()
                if "whatsapp" in window:
                    wa_result = (num, "wa-context")
                    break
                if wa_fallback is None:
                    wa_fallback = (num, "mobile")  # bare mobile: keep looking

        # Once the best possible WhatsApp signal and an email are both in
        # hand, further pages just cost time for no better answer.
        if wa_result and email:
            break

    return {"wa": wa_result or wa_fallback, "email": email}


def main(leads_path, out_path, country_key="uk", workers=16):
    country = COUNTRY_PATTERNS[country_key]
    leads = json.load(open(leads_path, encoding="utf-8"))
    sites = sorted({l["website"] for l in leads if l.get("website")})

    # Resume: never re-scan a site we already resolved.
    found = {}
    try:
        with open(out_path, encoding="utf-8") as f:
            found = json.load(f)
        print(f"resuming — {len(found)} already known")
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # A site from before email extraction was added lacks the "email" key —
    # rescan it once so it gets a fair chance at one too.
    todo = [s for s in sites if s not in found or "email" not in found[s]]
    print(f"scanning {len(todo)} of {len(sites)} websites…", flush=True)

    def save():
        # Write through a temp file so a kill can never truncate the results.
        tmp = out_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(found, f)
        os.replace(tmp, out_path)

    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(scan, s, country): s for s in todo}
        try:
            # A hung site can no longer hold the whole run hostage.
            for fut in concurrent.futures.as_completed(futures, timeout=SITE_DEADLINE * max(1, len(todo) // workers + 2)):
                site = futures[fut]
                done += 1
                try:
                    result = fut.result(timeout=1)
                except Exception:
                    result = None
                wa = result.get("wa") if result else None
                found[site] = {
                    "wa": wa[0] if wa else "",
                    "src": wa[1] if wa else "none",
                    "email": result.get("email", "") if result else "",
                }
                if done % 25 == 0:
                    save()  # checkpoint, so progress survives a kill
                    with_wa = sum(1 for v in found.values() if v["wa"])
                    with_email = sum(1 for v in found.values() if v.get("email"))
                    print(f"  {done}/{len(todo)} scanned — "
                          f"{with_wa} numbers, {with_email} emails", flush=True)
        except concurrent.futures.TimeoutError:
            print(f"  gave up waiting on {len(todo) - done} slow sites", flush=True)
            for f_ in futures:
                f_.cancel()

    save()
    with_wa = sum(1 for v in found.values() if v["wa"])
    wame = sum(1 for v in found.values() if v["src"] == "wa.me")
    with_email = sum(1 for v in found.values() if v.get("email"))
    print(f"\n{with_wa} WhatsApp numbers found across {len(sites)} sites")
    print(f"  {wame} from explicit wa.me links (high confidence)")
    print(f"  {with_wa - wame} from mobile numbers on the page (medium)")
    print(f"{with_email} email addresses found")
    print(f"written to {out_path}")


if __name__ == "__main__":
    a = sys.argv[1:]
    country_key = "uk"
    for flag in ("--uk", "--uae", "--usa"):
        if flag in a:
            country_key = flag[2:]
            a.remove(flag)
    default_leads = f"/tmp/leads_{country_key}.json" if country_key != "uk" else "/tmp/leads.json"
    default_out = f"whatsapp_{country_key}.json" if country_key != "uk" else "whatsapp.json"
    main(a[0] if a else default_leads, a[1] if len(a) > 1 else default_out,
         country_key=country_key)
