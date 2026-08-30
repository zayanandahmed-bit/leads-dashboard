#!/bin/bash
# Same pipeline as the UK batch, scoped to Dubai and Abu Dhabi.
cd "/Users/muhammadalizia/Desktop/claude code 1/Google-Maps-Scrapper"
source venv/bin/activate

VERTICALS=("dentist" "aesthetics clinic" "beauty salon" "estate agent")
CITIES=("Dubai" "Abu Dhabi")
OUT="uae_leads_master.csv"

run () {
  echo "=== Scraping: $1 ==="
  python main.py -s "$1" -t 100000 -o "$OUT" --append || echo "!!! FAILED: $1"
  sleep 8
}

for city in "${CITIES[@]}"; do
  for vertical in "${VERTICALS[@]}"; do
    run "$vertical in $city UAE"
  done
done

echo "BATCH_DONE"
