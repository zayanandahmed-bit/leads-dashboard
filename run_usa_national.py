"""
Nationwide US scrape: every (vertical x city) search from usa_cities.py,
run by a few parallel headless browsers.

Resumable — each finished search is recorded in raw_usa/_done.json, and
each search writes its own CSV, so a kill loses at most the searches that
were mid-flight. Re-run the same command to continue.

If Google serves a CAPTCHA / unusual-traffic page, every worker stops and
the run exits: we never try to get past it. Wait a while, then re-run.

    python run_usa_national.py [--workers 3] [--limit N]
"""

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from usa_cities import ALREADY_DONE, FAMOUS_CITIES, VERTICALS

RAW_DIR = "raw_usa"
DONE_PATH = os.path.join(RAW_DIR, "_done.json")
BLOCKED_EXIT = 3
SEARCH_TIMEOUT = 25 * 60  # a single search should never take this long

lock = threading.Lock()
blocked = threading.Event()


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def jobs():
    out = []
    for city, state in FAMOUS_CITIES:
        if (city, state) in ALREADY_DONE:
            continue
        for vertical in VERTICALS:
            query = f"{vertical} in {city} {state} USA"
            out.append((query, os.path.join(RAW_DIR, f"{slug(state)}__{slug(city)}__{slug(vertical)}.csv")))
    return out


def load_done():
    try:
        return json.load(open(DONE_PATH, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_done(done):
    tmp = DONE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(done, f, indent=0)
    os.replace(tmp, DONE_PATH)


def run_one(query, out_csv, done, total, started, visible=False):
    if blocked.is_set():
        return
    t0 = time.monotonic()
    code = None
    cmd = [sys.executable, "main.py", "-s", query, "-t", "100000", "-o", out_csv]
    if not visible:
        cmd.append("--headless")
    for attempt in (1, 2):
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=SEARCH_TIMEOUT,
            )
            code = proc.returncode
        except subprocess.TimeoutExpired:
            code = "timeout"
        if code == BLOCKED_EXIT:
            blocked.set()
            print(f"!!! Google blocked the scraper on: {query} — stopping all workers", flush=True)
            return
        if code == 0 or blocked.is_set():
            break
        time.sleep(20)  # transient failure: back off once, then retry

    rows = 0
    if os.path.exists(out_csv):
        with open(out_csv, encoding="utf-8") as f:
            rows = max(0, sum(1 for _ in f) - 1)

    with lock:
        done[query] = {"rows": rows, "ok": code == 0, "secs": round(time.monotonic() - t0)}
        save_done(done)
        n = len(done)
        elapsed = time.monotonic() - started
        rate = elapsed / max(1, n - started_count[0])
        remaining = (total - n) * rate
        status = "ok" if code == 0 else f"FAILED ({code})"
        print(f"[{n}/{total}] {status} {rows:>3} rows  {query}  "
              f"— ~{remaining / 3600:.1f}h left", flush=True)


started_count = [0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=7)
    ap.add_argument("--limit", type=int, default=0, help="only run this many pending searches (pilot)")
    ap.add_argument("--visible", action="store_true", help="show the Chrome window instead of running headless")
    args = ap.parse_args()

    os.makedirs(RAW_DIR, exist_ok=True)
    all_jobs = jobs()
    done = load_done()
    # A failed search gets another go on the next run.
    pending = [(q, p) for q, p in all_jobs if not done.get(q, {}).get("ok")]
    if args.limit:
        pending = pending[: args.limit]
    started_count[0] = len([q for q in done if done[q].get("ok")])

    print(f"{len(all_jobs)} searches total, {started_count[0]} already done, "
          f"running {len(pending)} with {args.workers} workers", flush=True)

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, (q, p) in enumerate(pending):
            ex.submit(run_one, q, p, done, len(all_jobs), started, args.visible)
            if i < args.workers:
                time.sleep(15)  # stagger browser start-up

    if blocked.is_set():
        print("BLOCKED — paused. Wait an hour or two, then re-run to resume.", flush=True)
        sys.exit(BLOCKED_EXIT)
    ok = sum(1 for v in done.values() if v.get("ok"))
    print(f"RUN_DONE — {ok}/{len(all_jobs)} searches complete, "
          f"{sum(v['rows'] for v in done.values())} raw rows", flush=True)


if __name__ == "__main__":
    main()
