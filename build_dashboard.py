"""Build the Signal Board from one or more countries' lead data.

Usage:
    python build_dashboard.py                # UK only (default)
    python build_dashboard.py --uae           # UAE only
    python build_dashboard.py --all           # UK + UAE combined, one page

Each country's CSV/enrichment/verification files stay separate
(uk_leads_master.csv vs uae_leads_master.csv, whatsapp.json vs
whatsapp_uae.json, ...) — this script just runs prep_leads.py once per
country and merges the results into a single leads.json for the page,
tagged with a "country" field the dashboard filters on.
"""

import json
import subprocess
import sys

SHELL = "dashboard_shell.html"
OUT = "signal_board.html"

DEFAULT_CSV = {"uk": "uk_leads_master.csv", "uae": "uae_leads_master.csv", "usa": "usa_leads_master.csv"}


def build_one(country_key, sources):
    out_path = f"/tmp/leads_{country_key}.json"
    subprocess.run(
        [sys.executable, "prep_leads.py", f"--{country_key}", *sources, out_path],
        check=True,
    )
    return json.load(open(out_path, encoding="utf-8"))


def main(args):
    if "--all" in args:
        countries = ["uk", "uae", "usa"]
        args.remove("--all")
    else:
        countries = ["uk"]
        for flag in ("--uk", "--uae", "--usa"):
            if flag in args:
                countries = [flag[2:]]
                args.remove(flag)

    all_leads = []
    for key in countries:
        sources = args if (args and len(countries) == 1) else [DEFAULT_CSV[key]]
        try:
            all_leads.extend(build_one(key, sources))
        except subprocess.CalledProcessError:
            print(f"skipping {key.upper()} — no data yet ({sources[0]} missing?)")

    all_leads.sort(key=lambda x: -x["score"])

    shell = open(SHELL, encoding="utf-8").read()
    leads_json = json.dumps(all_leads, ensure_ascii=False).replace("</", r"<\/")

    if "__LEADS__" not in shell:
        raise SystemExit(f"{SHELL} has no __LEADS__ placeholder")

    html = shell.replace("__LEADS__", leads_json)
    open(OUT, "w", encoding="utf-8").write(html)
    print(f"built {OUT}: {len(html):,} bytes, {len(all_leads)} leads "
          f"across {', '.join(c.upper() for c in countries)}")


if __name__ == "__main__":
    main(sys.argv[1:])
