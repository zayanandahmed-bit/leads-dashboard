"""
Supplementary WhatsApp-registration check via the public wa.me redirect
page — no Meta Business API, no Evolution/self-hosted session at all.

Visiting https://wa.me/<e164-number-no-plus> shows the account's own
profile NAME when one is visible to strangers. But this signal is
ASYMMETRIC, confirmed against Evolution's own results (see
check_accuracy() — 4 known-registered numbers checked by hand, 2 showed
their name and 2 didn't, even though Evolution confirmed all 4 are real
WhatsApp accounts):

  - A NAME showing IS a reliable positive — nobody unregistered has a
    WhatsApp profile name to show. Safe to treat as confirmed.
  - The generic "Chat on WhatsApp with +..." fallback is NOT a reliable
    negative — it appears both for numbers that truly aren't registered
    AND for real accounts whose privacy setting hides their name/photo
    from non-contacts. The two are indistinguishable from this page alone.

So this script only ever WRITES positive confirmations on top of what
Evolution already knows. It never marks anything "not on WhatsApp" —
doing that would silently mislabel privacy-locked real accounts as dead
numbers, which is worse than leaving them unchecked.

This never logs into a WhatsApp account, so there's no account-ban risk —
only the ordinary risk of WhatsApp's own bot defences rate-limiting or
blocking the IP if hit too fast. Each individual browser still paces
itself the same slow, randomised way; --workers runs several of them at
once (real parallelism, not a faster per-request delay) to cover a big
list in less wall-clock time. Every worker shares one kill-switch: the
moment ANY of them sees a rate-limit signal, all of them stop together
rather than ploughing on and finding out one by one. Resumable via
checkpointing so a stopped run picks back up instead of restarting.
"""

import argparse
import json
import os
import random
import re
import sys
import threading
import time

from playwright.sync_api import sync_playwright

CHECK_TIMEOUT = 15_000  # ms — a stalled page shouldn't hang the whole run
MIN_DELAY, MAX_DELAY = 3.0, 6.0  # seconds between checks — deliberately slow

NOT_REGISTERED_RE = re.compile(r"Chat on WhatsApp with", re.I)
BLOCKED_MARKERS = ("unusual traffic", "rate limit", "too many requests")


class RateLimited(Exception):
    pass


def check_one(page, number: str):
    """Returns True (registered, name shown), False (not registered),
    or None (inconclusive — invalid format, blocked, or timed out)."""
    page.goto(f"https://wa.me/{number}", timeout=CHECK_TIMEOUT, wait_until="domcontentloaded")
    page.wait_for_timeout(1200)  # the profile name renders client-side, after load
    text = page.inner_text("body")
    low = text.lower()
    if any(m in low for m in BLOCKED_MARKERS):
        raise RateLimited(number)
    if NOT_REGISTERED_RE.search(text):
        return False
    if "invalid" in low and "phone number" in low:
        return None  # malformed number, not a real answer either way
    # Any other heading text before "Open app" is the account's profile name.
    return True if "Open app" in text else None


def load_json(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    tmp = path + ".tmp"
    json.dump(data, open(tmp, "w", encoding="utf-8"))
    os.replace(tmp, path)


def check_accuracy(wa_verified_path="wa_verified.json", sample=20):
    """Sanity check: run this method against numbers Evolution already
    scored, and report agreement, before trusting it on anything unchecked."""
    verified = load_json(wa_verified_path, {})
    trues = [k for k, v in verified.items() if v is True]
    falses = [k for k, v in verified.items() if v is False]
    random.shuffle(trues)
    random.shuffle(falses)
    probe = [(n, True) for n in trues[:sample]] + [(n, False) for n in falses[:sample]]
    random.shuffle(probe)

    # Tracked separately, not as one blended score — the two directions have
    # very different reliability (see module docstring) and averaging them
    # into one number would hide that.
    true_hit = true_miss = false_hit = false_miss = inconclusive = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        for number, expected in probe:
            try:
                got = check_one(page, number)
            except RateLimited:
                print("!!! Rate-limited by WhatsApp — stopping accuracy check early", flush=True)
                break
            if got is None:
                inconclusive += 1
            elif expected is True:
                true_hit += got is True
                true_miss += got is False
            else:
                false_hit += got is False
                false_miss += got is True  # would be a real problem: a false positive
            if got != expected:
                print(f"  MISMATCH {number}: Evolution said {expected}, wa.me said {got}", flush=True)
            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
        browser.close()

    t_total, f_total = true_hit + true_miss, false_hit + false_miss
    print(f"\nOn Evolution-confirmed REGISTERED numbers: "
          f"{true_hit}/{t_total} showed a name (the rest are real accounts wa.me can't see into)")
    print(f"On Evolution-confirmed NOT-registered numbers: "
          f"{false_hit}/{f_total} correctly showed no name"
          + (f" — {false_miss} showed a name anyway (a real false positive, investigate)" if false_miss else ""))
    return true_hit, true_miss, false_hit, false_miss, inconclusive


_lock = threading.Lock()
_blocked = threading.Event()
_stats = {"done": 0, "confirmed": 0, "inconclusive": 0}


def _worker(number_slice, results, out_path):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        for number in number_slice:
            if _blocked.is_set():
                break
            try:
                got = check_one(page, number)
            except RateLimited:
                _blocked.set()
                print("!!! Rate-limited by WhatsApp — stopping ALL workers. "
                      "Progress so far is saved; wait a while before resuming.", flush=True)
                break
            except Exception as e:
                got = None
                print(f"  error on {number}: {e}", flush=True)

            with _lock:
                _stats["done"] += 1
                if got is True:
                    results[number] = True
                    _stats["confirmed"] += 1
                elif got is False:
                    results[number] = False  # checked, inconclusive — NOT "not on WhatsApp"
                # got is None (error/invalid format): not recorded, genuinely untried
                if _stats["done"] % 10 == 0:
                    save_json(out_path, results)
                    inc = sum(1 for v in results.values() if v is False)
                    print(f"  {_stats['done']} checked — {_stats['confirmed']} confirmed on WhatsApp, "
                          f"{inc} inconclusive (name hidden or not registered — can't tell)", flush=True)
            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
        browser.close()


def run_batch(leads_paths, out_path, limit, workers=1, wa_verified_path="wa_verified.json"):
    """Records BOTH outcomes, but they mean different things:
      true  = a profile name showed — reliable confirmation, as good as Evolution.
      false = only the number echoed back — recorded so the dashboard can say
              "we checked, no name" honestly, but NEVER treated as "not on
              WhatsApp" (see module docstring — a real, privacy-locked
              account looks identical). Errors/rate-limits/invalid formats
              (None) are not recorded at all — genuinely not attempted.

    Runs `workers` browsers in parallel, each pacing itself the same slow
    way as before — this covers a big list faster in wall-clock time
    without making any single stream of requests look more aggressive to
    WhatsApp than the already-validated single-worker pace."""
    leads = []
    for path in leads_paths:
        leads.extend(json.load(open(path, encoding="utf-8")))
    verified = load_json(wa_verified_path, {})
    results = load_json(out_path, {})

    # Only worth checking numbers Evolution hasn't already settled, and that
    # our pipeline actually produced a candidate for.
    candidates = sorted({
        l["wa"] for l in leads
        if l.get("wa") and l["wa"] not in verified and l["wa"] not in results
    })
    todo = candidates[:limit] if limit else candidates
    per_worker_secs = len(todo) / max(1, workers) * (MIN_DELAY + MAX_DELAY) / 2
    print(f"{len(candidates)} unchecked numbers available, checking {len(todo)} this run "
          f"with {workers} worker(s) (~{round(per_worker_secs / 60)} min at this pace)", flush=True)

    slices = [todo[i::workers] for i in range(workers)]  # interleaved, so each
    # worker's early failures don't all land on the same city/country block
    threads = [threading.Thread(target=_worker, args=(s, results, out_path)) for s in slices]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    save_json(out_path, results)
    inconclusive = sum(1 for v in results.values() if v is False)
    print(f"\nchecked {_stats['done']} — {_stats['confirmed']} newly confirmed, {inconclusive} inconclusive — "
          f"saved {len(results)} total results to {out_path}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--accuracy-check", action="store_true",
                     help="validate against known Evolution results instead of checking new numbers")
    ap.add_argument("--sample", type=int, default=20, help="pairs to sample for --accuracy-check")
    ap.add_argument("leads", nargs="*", help="one or more leads JSON files to pull unchecked numbers from")
    ap.add_argument("--out", default="wa_redirect_checked.json")
    ap.add_argument("--limit", type=int, default=50, help="max new numbers to check this run (0 = all)")
    ap.add_argument("--workers", type=int, default=1, help="parallel browsers (real concurrency, same per-worker pace)")
    args = ap.parse_args()

    if args.accuracy_check:
        check_accuracy(sample=args.sample)
    else:
        if not args.leads:
            sys.exit("usage: wa_redirect_check.py <leads.json> [<leads2.json> ...] [--out FILE] [--limit N] [--workers N]")
        run_batch(args.leads, args.out, args.limit, workers=args.workers)
