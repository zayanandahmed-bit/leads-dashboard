#!/bin/bash
cd "/Users/muhammadalizia/Desktop/claude code 1/Google-Maps-Scrapper"
source venv/bin/activate

VERTICALS=("dentist" "aesthetics clinic" "beauty salon" "estate agent")
CITIES=("London" "Manchester" "Birmingham" "Leeds")
OUT="uk_leads_master.csv"

for city in "${CITIES[@]}"; do
  for vertical in "${VERTICALS[@]}"; do
    echo "=== Scraping: $vertical in $city ==="
    python main.py -s "$vertical in $city UK" -t 100000 -o "$OUT" --append
    sleep 8
  done
done
echo "BATCH_DONE"
