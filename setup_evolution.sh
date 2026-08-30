#!/bin/bash
# One-time Evolution API setup, then verify every number in the pipeline.
#
# Run this in your own terminal. Your API key is typed directly into your
# machine and written to .env (gitignored, owner-read-only). It never passes
# through a chat transcript.
#
#   ./setup_evolution.sh

cd "$(dirname "$0")" || exit 1

echo
echo "Evolution API setup"
echo "==================="

if [ -f .env ]; then
  echo
  echo ".env already exists — re-using it."
  echo "(Delete it and re-run this script to change the values.)"
else
  echo
  echo "1) Where is Evolution running?"
  echo "   Docker on this Mac  ->  http://localhost:8080"
  echo "   On a server         ->  http://YOUR-SERVER-IP:8080"
  read -r -p "   API URL [http://localhost:8080]: " URL
  URL=${URL:-http://localhost:8080}
  URL=${URL%/}

  echo
  echo "2) Your API key."
  echo "   It's AUTHENTICATION_API_KEY in Evolution's own .env / docker-compose.yml."
  echo
  echo "   NOTE: the key is hidden as you type — you will see NOTHING on screen,"
  echo "   not even dots. That is normal (same as a sudo password)."
  echo "   Paste with Cmd+V, then press Enter."
  echo
  read -r -s -p "   API key: " KEY
  echo
  while [ -z "$KEY" ]; do
    echo "   Nothing received — paste the key and press Enter."
    read -r -s -p "   API key: " KEY
    echo
  done
  # Confirm receipt without ever printing the key itself.
  echo "   Received a key of ${#KEY} characters, ending …${KEY: -4}"

  echo
  echo "3) Looking up your instances…"
  INSTANCES=$(curl -s -m 20 -H "apikey: $KEY" "$URL/instance/fetchInstances" 2>/dev/null)

  if [ -z "$INSTANCES" ]; then
    echo "   Couldn't reach $URL — is Evolution running?"
    echo "   Check with:  curl $URL"
    exit 1
  fi

  # Parse whichever shape this Evolution version returns.
  PARSED=$(printf '%s' "$INSTANCES" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(1)
rows = d if isinstance(d, list) else d.get("instances", d.get("data", []))
out = []
for r in rows or []:
    if not isinstance(r, dict):
        continue
    inner = r.get("instance") if isinstance(r.get("instance"), dict) else r
    name = inner.get("instanceName") or inner.get("name") or inner.get("id")
    state = (inner.get("connectionStatus") or inner.get("status")
             or inner.get("state") or "unknown")
    if name:
        out.append(f"{name}\t{state}")
print("\n".join(out))
' 2>/dev/null)

  if [ -z "$PARSED" ]; then
    echo "   Server answered but listed no instances."
    echo "   Raw response:"
    printf '   %s\n' "$(printf '%s' "$INSTANCES" | head -c 300)"
    echo
    echo "   If that says 'Unauthorized', the API key is wrong."
    echo "   Otherwise create an instance in Evolution first, then re-run."
    exit 1
  fi

  echo
  echo "   Found:"
  i=0
  NAMES=()
  while IFS=$'\t' read -r name state; do
    i=$((i+1))
    NAMES+=("$name")
    printf "     %d) %-28s %s\n" "$i" "$name" "$state"
  done <<< "$PARSED"

  echo
  if [ "$i" -eq 1 ]; then
    INSTANCE="${NAMES[0]}"
    echo "   Using: $INSTANCE"
  else
    read -r -p "   Pick a number [1]: " PICK
    PICK=${PICK:-1}
    INSTANCE="${NAMES[$((PICK-1))]}"
    [ -z "$INSTANCE" ] && { echo "   Invalid choice."; exit 1; }
    echo "   Using: $INSTANCE"
  fi

  umask 077                      # create .env as owner-read-only
  cat > .env <<EOF
EVOLUTION_API_URL=$URL
EVOLUTION_INSTANCE=$INSTANCE
EVOLUTION_API_KEY=$KEY
EOF
  chmod 600 .env
  unset KEY
  echo
  echo "   Saved to .env (permissions 600, gitignored)."
fi

echo
echo "Checking the connection…"
source venv/bin/activate || { echo "venv missing — run this from the scraper folder"; exit 1; }

python - <<'PY'
import json, sys, urllib.request, urllib.error
sys.path.insert(0, ".")
from verify_whatsapp import config

url, key, inst = config()
try:
    import urllib.parse
    req = urllib.request.Request(
        f"{url}/instance/connectionState/{urllib.parse.quote(inst, safe='')}",
        headers={"apikey": key},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode())
    state = (data.get("instance") or data).get("state", data)
    print(f"  instance '{inst}': {state}")
    if str(state).lower() not in ("open", "connected"):
        print("  Not connected — open Evolution and scan the QR, then re-run.")
        sys.exit(1)
except urllib.error.HTTPError as e:
    sys.exit(f"  HTTP {e.code}: {e.read().decode('utf-8','ignore')[:200]}")
except Exception as e:
    sys.exit(f"  Cannot reach {url} — is Evolution running? ({e})")
PY

if [ $? -ne 0 ]; then
  echo
  echo "Fix the above, then re-run this script."
  exit 1
fi

echo
echo "Verifying numbers…"
python verify_whatsapp.py || exit 1

echo
echo "Rebuilding the dashboard…"
python build_dashboard.py uk_leads_master.csv

echo
echo "Done — tell Claude to republish."
