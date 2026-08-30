"""
Turn raw Google Maps scrape output into scored, deduplicated leads for the
WhatsApp-automation pipeline dashboard.

Scoring model: the thing we are actually selling is absorbing repetitive
inbound WhatsApp messages. So the buying signal is message VOLUME plus
out-of-hours exposure, not company size.
"""

import csv
import json
import math
import re
import sys

# Order matters: the first rule that matches wins, so the more specific
# sectors are listed before the catch-all clinical ones. Verticals themselves
# are universal — dentists and salons look the same everywhere — only the
# country-specific bits below (numbers, cities) actually vary.
VERTICAL_RULES = [
    ("Dental", ("dentist", "dental", "orthodont", "endodont", "periodont", "teeth", "implant")),
    ("Aesthetics", (
        "aesthetic", "medical spa", "med spa", "skin", "cosmetic", "laser", "botox",
        "dermatolog", "plastic surgeon", "permanent make-up", "permanent makeup",
        "tattoo removal", "hair removal", "weight loss", "wellness cent",
    )),
    ("Salon & Spa", (
        "salon", "spa", "barber", "nail", "hair", "beauty", "beautician",
        "waxing", "lash", "eyebrow", "massage", "facial",
    )),
    ("Property", ("estate agent", "real estate", "letting", "property")),
    ("Legal & Immigration", (
        "immigration", "attorney", "law firm", "lawyer", "legal service",
        "notario", "visa consult", "law office",
    )),
    # Catch-all for the generic clinical listings Maps returns alongside the above.
    ("Medical", ("clinic", "doctor", "medical", "physician", "surgery", "health")),
]

# Booking platforms, social profiles and link-in-bio tools that Maps
# sometimes lists as a business's "website". Scanning one of these finds the
# PLATFORM's own contact details, not the business's — and since hundreds of
# unrelated businesses share the same root domain, it also breaks dedup keys
# that assume a website belongs to one business. Never trust one for
# enrichment lookups or as a dedup key; still fine to show as a raw link.
PLATFORM_DOMAINS = {
    "fresha.com", "instagram.com", "facebook.com", "linktr.ee", "linktree.com",
    "twitter.com", "x.com", "tiktok.com", "booksy.com", "treatwell.co.uk",
    "wa.me", "m.me", "g.page", "goo.gl", "bit.ly", "maps.google.com",
    "wixsite.com", "square.site", "setmore.com", "calendly.com",
}


def is_platform_domain(website: str) -> bool:
    w = (website or "").lower().lstrip("www.")
    return w in PLATFORM_DOMAINS


# Per-country phone/geography rules. `mobile_re` matches a full E.164 (no +)
# number that is capable of running WhatsApp; `cities` seeds derive_city
# before it falls back to parsing the address line; `strip` removes
# country-specific address noise (a UK postcode, a UAE PO Box) so the
# fallback city name comes out clean.
COUNTRIES = {
    "uk": {
        "cc": "44",
        "mobile_re": re.compile(r"^447\d{9}$"),
        "cities": ["London", "Manchester", "Birmingham", "Leeds", "Glasgow",
                   "Liverpool", "Bristol", "Sheffield", "Edinburgh", "Cardiff",
                   "Nottingham", "Newcastle"],
        "strip": re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.I),  # postcode
        "drop_tokens": ("united kingdom", "uk"),
    },
    "uae": {
        "cc": "971",
        # UAE mobiles: 05X XXX XXXX nationally -> 971 5X XXXXXXX (5 is the
        # mobile lead digit; 0-prefixed 50/52/54/55/56/58 ranges).
        "mobile_re": re.compile(r"^9715[0245689]\d{7}$"),
        "cities": ["Dubai", "Abu Dhabi"],
        "strip": re.compile(r"\bP\.?O\.?\s*Box\s*\d+\b", re.I),
        "drop_tokens": ("united arab emirates", "uae"),
    },
    "usa": {
        "cc": "1",
        # NANP has no reserved mobile range — a landline and a mobile are the
        # same shape (1 + 10 digits). We can't tell them apart from the
        # number alone, so treat every valid number as a candidate and let
        # Evolution be the actual judge, rather than guessing "mobile".
        "mobile_re": re.compile(r"^1\d{10}$"),
        "cities": ["Miami", "Hialeah", "Fort Lauderdale", "Houston", "Dallas",
                   "Los Angeles", "New York", "Newark", "Jersey City"],
        "strip": re.compile(r"\b\d{5}(-\d{4})?\b"),  # ZIP / ZIP+4
        "drop_tokens": ("united states", "usa", "us"),
    },
}


def to_e164(raw: str, cc: str) -> str:
    """Digits only, normalised to <cc>xxxxxxxxxx."""
    n = re.sub(r"[^\d]", "", raw or "")
    if n.startswith("00"):
        n = n[2:]
    if n.startswith(cc):
        return n
    if n.startswith("0"):
        n = n[1:]
    return cc + n


def derive_city(address: str, country: dict) -> str:
    for city in country["cities"]:
        if re.search(rf"\b{re.escape(city)}\b", address, re.I):
            return city
    # Fall back to the last address line, minus postcode/PO-box and country name.
    # Some addresses use " - " rather than "," as the segment separator.
    raw_parts = address.split(",") if "," in address else address.split(" - ")
    parts = [p.strip() for p in raw_parts if p.strip()]
    parts = [p for p in parts if p.lower() not in country["drop_tokens"]]
    for part in reversed(parts):
        town = country["strip"].sub("", part).strip(" ,")
        # A real fallback town name is short; anything longer is an
        # unparsed address fragment, not a place name — don't show that.
        if town and len(town) <= 24:
            return town
    return "Other"


def derive_vertical(place_type: str) -> str:
    pt = (place_type or "").lower()
    for label, needles in VERTICAL_RULES:
        if any(n in pt for n in needles):
            return label
    return place_type.strip() or "Other"


def closing_hour(opens_at: str) -> int | None:
    """Return closing time as a 24h integer, or None when unknown."""
    m = re.search(r"Closes\s*(\d{1,2})(?::(\d{2}))?\s*(AM|PM)", opens_at or "", re.I)
    if not m:
        return None
    hour = int(m.group(1))
    meridiem = m.group(3).upper()
    if meridiem == "PM" and hour != 12:
        hour += 12
    if meridiem == "AM" and hour == 12:
        hour = 0
    return hour


def score_lead(reviews: int, rating: float | None, close_h: int | None, website: str):
    """0-100 opportunity score plus the reasons behind it."""
    reasons = []

    # Message volume proxy: review count on a log curve. Weighted to dominate
    # the score, because volume is the whole reason automation pays for itself.
    # Anchored so ~50 reviews scores low and ~2000 saturates.
    if reviews > 0:
        volume = min(55, round((math.log10(reviews + 1) - 1.3) / (math.log10(2000) - 1.3) * 55))
        volume = max(0, volume)
    else:
        volume = 0
    if reviews >= 800:
        reasons.append(f"{reviews:,} reviews — very high customer throughput")
    elif reviews >= 300:
        reasons.append(f"{reviews:,} reviews — steady inbound volume")
    elif reviews > 0:
        reasons.append(f"{reviews:,} reviews")

    # Out-of-hours exposure: late closers collect messages staff can't answer.
    if close_h is None:
        hours = 6
    elif close_h >= 19:
        hours = 20
        reasons.append(f"Open to {close_h - 12}PM — heavy after-hours enquiry load")
    elif close_h >= 18:
        hours = 12
        reasons.append(f"Closes {close_h - 12}PM — evening enquiries go unanswered")
    else:
        hours = 5

    # A website means a digital front door already funnelling enquiries.
    # Near-universal in this market, so it's worth little as a differentiator.
    web = 10 if website else 0

    # Rating as a proxy for a healthy practice that can afford tooling.
    if rating is None:
        rate = 4
    elif rating >= 4.7:
        rate = 15
        reasons.append(f"{rating} rating — established, has budget")
    elif rating >= 4.3:
        rate = 10
    elif rating >= 4.0:
        rate = 6
    else:
        rate = 2

    return min(100, volume + hours + web + rate), reasons


def band(score: int) -> str:
    # Thresholds set against the observed distribution so the top band stays
    # small enough to actually be a call list.
    if score >= 75:
        return "prime"
    if score >= 55:
        return "strong"
    return "watch"


def load(paths):
    rows = []
    for path in paths:
        try:
            with open(path, newline="", encoding="utf-8") as f:
                rows.extend(list(csv.DictReader(f)))
        except FileNotFoundError:
            print(f"skip (missing): {path}", file=sys.stderr)
    return rows


def main(paths, out_path, enrich_path="whatsapp.json", country_key="uk"):
    country = COUNTRIES[country_key]
    cc = country["cc"]
    raw = load(paths)
    seen = {}

    try:
        with open(enrich_path, encoding="utf-8") as f:
            enrichment = json.load(f)
        print(f"loaded {len(enrichment)} discovered WhatsApp numbers")
    except (FileNotFoundError, json.JSONDecodeError):
        enrichment = {}
        print("no whatsapp.json — run enrich_whatsapp.py to find real WhatsApp numbers")

    # A number found on several DIFFERENT websites belongs to a third party —
    # the web designer, booking platform or agency in the footer — not to any
    # of those businesses. Messaging it would reach the wrong person, and it
    # verifies as live on WhatsApp, so it can't be caught downstream.
    site_count = {}
    for site, rec in enrichment.items():
        if rec.get("wa"):  # skip sites where nothing was found
            site_count.setdefault(rec["wa"], set()).add(site)
    shared_numbers = {n for n, sites in site_count.items() if len(sites) > 1}
    if shared_numbers:
        print(f"dropping {len(shared_numbers)} numbers found on multiple "
              f"unrelated sites (third-party/agency numbers)")

    # Ground truth from Evolution API, when it's been run.
    try:
        with open("wa_verified.json", encoding="utf-8") as f:
            verified = json.load(f)
        live = sum(1 for v in verified.values() if v)
        print(f"loaded {len(verified)} Evolution checks — {live} confirmed on WhatsApp")
    except (FileNotFoundError, json.JSONDecodeError):
        verified = {}

    for r in raw:
        name = (r.get("name") or "").strip()
        phone = (r.get("phone_number") or "").strip()
        website = (r.get("website") or "").strip()

        # A platform root (fresha.com, instagram.com, ...) isn't this
        # business's own site — it's shared by everyone who uses that
        # platform. Trust it for display, never for dedup or enrichment
        # lookups: scanning it would find the PLATFORM's contact details,
        # not this business's, and its shared root breaks the dedup key.
        lookup_site = "" if is_platform_domain(website) else website

        # Keep anything we can actually reach. A listing with no phone and
        # only a platform link (or none) is neither reachable nor de-dupeable.
        if not name or not (phone or lookup_site):
            continue

        key = phone.replace(" ", "") if phone else "site:" + lookup_site.lower()
        if key in seen:
            continue

        address = (r.get("address") or "").strip()
        city = derive_city(address, country)
        try:
            reviews = int(r.get("reviews_count") or 0)
        except ValueError:
            reviews = 0
        try:
            rating = float(r.get("reviews_average") or 0) or None
        except ValueError:
            rating = None

        close_h = closing_hour(r.get("opens_at") or "")
        score, reasons = score_lead(reviews, rating, close_h, website)

        # The listed number is usually the reception landline, which is never
        # on WhatsApp. Prefer a mobile discovered on the business's own site.
        found = enrichment.get(lookup_site) if lookup_site else None
        if found and found["wa"] in shared_numbers:
            found = None  # third-party number, not this business's

        # Candidates in preference order: the number the business publishes on
        # its own site, then whatever Maps listed. The Maps number is usually a
        # landline, but WhatsApp Business can be registered to one — so it is
        # still worth offering to Evolution rather than assuming.
        candidates = []
        if found:
            candidates.append((found["wa"], found["src"]))
        listed = to_e164(phone, cc)
        if listed and listed.startswith(cc) and 9 <= len(listed) <= 13:
            is_mobile = bool(country["mobile_re"].match(listed))
            candidates.append((listed, "listed" if is_mobile else "listed-landline"))

        wa_number, wa_source = "", "none"
        # Prefer any candidate Evolution has confirmed; fall back to the first
        # unchecked one so nothing silently disappears before verification.
        for num, src in candidates:
            if verified.get(num) is True:
                wa_number, wa_source = num, "verified"
                break
        else:
            for num, src in candidates:
                if num not in verified:
                    wa_number, wa_source = num, src
                    break
            else:
                if candidates:
                    wa_number, wa_source = candidates[0][0], "not-registered"

        email = (enrichment.get(lookup_site, {}).get("email") if lookup_site else "") or ""

        seen[key] = {
            "id": key,
            "name": name,
            "country": country_key.upper(),
            "address": address,
            "city": city,
            "vertical": derive_vertical(r.get("place_type") or ""),
            "type": (r.get("place_type") or "").strip(),
            "website": website,
            "phone": phone,
            "email": email,
            "wa": wa_number,
            "waSrc": wa_source,
            "reviews": reviews,
            "rating": rating,
            "closes": close_h,
            "score": score,
            "band": band(score),
            "reasons": reasons,
        }

    leads = sorted(seen.values(), key=lambda x: -x["score"])

    # Final sweep, whatever the number's source: if one number serves several
    # businesses with different websites, it isn't any of theirs. (Branches of
    # one chain share a website, so those are left alone.)
    sites_per_number = {}
    for l in leads:
        if l["wa"]:
            sites_per_number.setdefault(l["wa"], set()).add(l["website"])
    third_party = {n for n, s in sites_per_number.items() if len(s) > 1}
    if third_party:
        cleared = 0
        for l in leads:
            if l["wa"] in third_party:
                l["wa"], l["waSrc"] = "", "none"
                cleared += 1
        print(f"cleared {cleared} leads using {len(third_party)} shared third-party numbers")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(leads, f, ensure_ascii=False)

    print(f"{len(leads)} leads written to {out_path}")
    for b in ("prime", "strong", "watch"):
        print(f"  {b}: {sum(1 for l in leads if l['band'] == b)}")

    # A number Evolution rejected is not reachable, whatever the website said.
    reachable = sum(1 for l in leads if l["wa"] and l["waSrc"] != "not-registered")
    confirmed = sum(1 for l in leads if l["waSrc"] == "verified")
    dead = sum(1 for l in leads if l["waSrc"] == "not-registered")
    print(f"  WhatsApp-reachable: {reachable} / {len(leads)}"
          f"  (verified {confirmed}, unchecked {reachable - confirmed}, ruled out {dead})")
    print(f"  with an email address: {sum(1 for l in leads if l['email'])} / {len(leads)}")


if __name__ == "__main__":
    args = sys.argv[1:]
    country_key = "uk"
    for flag in ("--uk", "--uae", "--usa"):
        if flag in args:
            country_key = flag[2:]
            args.remove(flag)
    out = args.pop() if len(args) > 1 else "leads.json"
    default_csv = f"{country_key}_leads_master.csv"
    enrich_path = "whatsapp.json" if country_key == "uk" else f"whatsapp_{country_key}.json"
    main(args or [default_csv], out, enrich_path=enrich_path, country_key=country_key)
