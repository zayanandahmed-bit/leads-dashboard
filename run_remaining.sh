#!/bin/bash
# Resume the batch from where it died (searches 10-16). Each search appends,
# and prep_leads.py dedupes by phone number, so re-running one is harmless.
cd "/Users/muhammadalizia/Desktop/claude code 1/Google-Maps-Scrapper"
source venv/bin/activate

OUT="uk_leads_master.csv"

run () {
  echo "=== Scraping: $1 ==="
  # Don't let one failed search kill the whole run.
  python main.py -s "$1" -t 100000 -o "$OUT" --append || echo "!!! FAILED: $1"
  sleep 8
}

run "aesthetics clinic in Birmingham UK"
run "beauty salon in Birmingham UK"
run "estate agent in Birmingham UK"
run "dentist in Leeds UK"
run "aesthetics clinic in Leeds UK"
run "beauty salon in Leeds UK"
run "estate agent in Leeds UK"

echo "BATCH_DONE"
