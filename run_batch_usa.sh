#!/bin/bash
# Same pipeline as UK/UAE, scoped to WhatsApp-heavy US metros — diaspora-
# dense areas where WhatsApp is the default channel, not SMS/iMessage.
cd "/Users/muhammadalizia/Desktop/claude code 1/Google-Maps-Scrapper"
source venv/bin/activate

VERTICALS=("dentist" "aesthetics clinic" "beauty salon" "real estate agent" "immigration lawyer")
CITIES=("Miami FL" "Houston TX" "Dallas TX" "Los Angeles CA" "New York NY")
OUT="usa_leads_master.csv"

run () {
  echo "=== Scraping: $1 ==="
  python main.py -s "$1" -t 100000 -o "$OUT" --append || echo "!!! FAILED: $1"
  sleep 8
}

for city in "${CITIES[@]}"; do
  for vertical in "${VERTICALS[@]}"; do
    run "$vertical in $city USA"
  done
done

echo "BATCH_DONE"
