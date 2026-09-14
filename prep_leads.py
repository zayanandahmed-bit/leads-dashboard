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

from usa_cities import USA_CITIES

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
        "valid_len": {12},  # "44" + 10-digit national number (mobile or landline)
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
        # UAE, unlike UK/USA, has two valid national lengths: a mobile is
        # "971" + 9 digits (12 total) but a landline is only 8 digits
        # nationally ("971" + single-digit area code + 7 local = 11 total).
        "valid_len": {11, 12},
        "cities": ["Dubai", "Abu Dhabi"],
        "strip": re.compile(r"\bP\.?O\.?\s*Box\s*\d+\b", re.I),
        "drop_tokens": ("united arab emirates", "uae"),
    },
    "usa": {
        "cc": "1",
        # NANP has no reserved mobile range — a landline and a mobile are the
        # same shape (1 + 10 digits). We can't tell them apart from the
        # number alone, so treat every valid number as a candidate and let
        # Evolution be the actual judge, rather than guessing "mobile". Still
        # requires real NANP structure (area/exchange code can't start 0/1) —
        # otherwise a garbage digit run from Maps gets treated as a candidate.
        "mobile_re": re.compile(r"^1[2-9]\d{2}[2-9]\d{6}$"),
        "valid_len": {11},  # "1" + 10-digit NANP number
        # Every city the nationwide scrape searched, longest names first so
        # "North Las Vegas" wins over "Las Vegas" and "West Fargo" over "Fargo".
        "cities": sorted({c for cs in USA_CITIES.values() for c in cs}
                         | {"Hialeah", "Fort Lauderdale"}, key=len, reverse=True),
        "strip": re.compile(r"\b\d{5}(-\d{4})?\b"),  # ZIP / ZIP+4
        # "..., Coral Gables, FL 33134" -> the segment right before "ST ZIP".
        "city_re": re.compile(r"([^,]+),\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?\b"),
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
    # Prefer the address's own structure where the country has a reliable one;
    # street names like "Washington St" make a whole-address name search lie.
    if country.get("city_re"):
        m = country["city_re"].search(address)
        if m:
            town = m.group(1).strip()
            if 2 < len(town) <= 30 and not re.match(r"^\d", town):
                return town
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
        # A bare 2-letter code ("FL", "CA") is a US state abbreviation left
        # over after stripping the ZIP from "City, FL 33101" — not a city.
        if town and 2 < len(town) <= 24 and not re.fullmatch(r"[A-Z]{2}", town):
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

    # Same problem, same fix, for email domains: a domain that shows up on
    # many unrelated businesses' sites isn't any one of theirs — it's a
    # platform/CRM/template/font-license address in shared boilerplate
    # (a real-estate platform's own domain, a website builder's default
    # contact, a font vendor's licence comment). A personal-webmail domain
    # legitimately repeats across unrelated businesses, so those are exempt.
    PERSONAL_EMAIL_DOMAINS = {
        "gmail.com", "yahoo.com", "icloud.com", "aol.com", "outlook.com",
        "hotmail.com", "live.com", "msn.com", "protonmail.com", "me.com",
        "comcast.net", "att.net", "verizon.net",
    }
    domain_sites = {}
    for site, rec in enrichment.items():
        email = (rec.get("email") or "").lower()
        if email and "@" in email:
            domain_sites.setdefault(email.split("@")[1], set()).add(site)
    shared_email_domains = {
        d for d, sites in domain_sites.items()
        if len(sites) > 2 and d not in PERSONAL_EMAIL_DOMAINS
    }
    if shared_email_domains:
        print(f"dropping emails at {len(shared_email_domains)} shared/template domains "
              f"(platform or vendor addresses, not the business's own)")

    # Ground truth from Evolution API, when it's been run.
    try:
        with open("wa_verified.json", encoding="utf-8") as f:
            verified = json.load(f)
        live = sum(1 for v in verified.values() if v)
        print(f"loaded {len(verified)} Evolution checks — {live} confirmed on WhatsApp")
    except (FileNotFoundError, json.JSONDecodeError):
        verified = {}

    # Supplementary check via the public wa.me page (wa_redirect_check.py).
    # true  = a profile name showed up — as reliable as Evolution's "yes".
    # false = only the number echoed back — genuinely inconclusive, NOT a
    #         "no" (a real account with a private profile looks identical
    #         to an unregistered one on this page). Never used to rule a
    #         number out, only to add extra confirmed positives.
    try:
        with open("wa_redirect_checked.json", encoding="utf-8") as f:
            redirect_checked = json.load(f)
        confirmed = sum(1 for v in redirect_checked.values() if v)
        print(f"loaded {len(redirect_checked)} wa.me checks — {confirmed} confirmed by profile name")
    except (FileNotFoundError, json.JSONDecodeError):
        redirect_checked = {}

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
        # enrichment.get() returns a record for every scanned site, even one
        # where nothing was found ({"wa": "", "src": "none"}) — that record is
        # truthy, so it must never stand in for "found a number" on its own,
        # or a scanned-but-empty site silently loses its listed fallback.
        found = enrichment.get(lookup_site) if lookup_site else None
        if found and not found.get("wa"):
            found = None  # scanned, nothing found — not a real candidate
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
        # Exact length per country, not a loose 9-13 range: a generic range
        # let junk like an appended extension digit ("...1235 ext. 5" -> a
        # 12-digit US string) through as a "landline" candidate even though
        # it was never a real number to begin with.
        if listed and listed.startswith(cc) and len(listed) in country["valid_len"]:
            is_mobile = bool(country["mobile_re"].match(listed))
            candidates.append((listed, "listed" if is_mobile else "listed-landline"))

        wa_number, wa_source = "", "none"
        # Prefer any candidate Evolution or the wa.me name-check has already
        # confirmed positive; fall back to the first unchecked one so nothing
        # silently disappears before verification.
        for num, src in candidates:
            if verified.get(num) is True:
                wa_number, wa_source = num, "verified"
                break
            if redirect_checked.get(num) is True:
                wa_number, wa_source = num, "confirmed-wa.me"
                break
        else:
            for num, src in candidates:
                if num not in verified:
                    wa_number, wa_source = num, src
                    break
            else:
                if candidates:
                    wa_number, wa_source = candidates[0][0], "not-registered"

        # A number the wa.me check actually looked at but couldn't confirm
        # (no profile name shown — genuinely inconclusive, not a "no", see
        # the loader comment above) stays exactly as unchecked as before,
        # but this flag lets the drawer say "we did try this one" honestly.
        wa_redirect_tried = (wa_source not in ("verified", "confirmed-wa.me", "not-registered")
                              and redirect_checked.get(wa_number) is False)

        email = (enrichment.get(lookup_site, {}).get("email") if lookup_site else "") or ""
        if email and email.split("@")[-1] in shared_email_domains:
            email = ""  # platform/vendor address, not this business's own

        # US addresses end "City, ST 12345" — the state code is right before the ZIP.
        state = ""
        if country_key == "usa":
            m = re.search(r",\s*([A-Z]{2})\s+\d{5}(?:-\d{4})?\b", address)
            if m and m.group(1) in USA_CITIES:
                state = m.group(1)

        seen[key] = {
            "id": key,
            "name": name,
            "country": country_key.upper(),
            "address": address,
            "state": state,
            "city": city,
            "vertical": derive_vertical(r.get("place_type") or ""),
            "type": (r.get("place_type") or "").strip(),
            "website": website,
            "phone": phone,
            "email": email,
            "wa": wa_number,
            "waSrc": wa_source,
            "waTried": wa_redirect_tried,
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
    confirmed = sum(1 for l in leads if l["waSrc"] in ("verified", "confirmed-wa.me"))
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
