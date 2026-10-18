#!/usr/bin/env bash
# Expose your local backend to Twilio with ngrok, then point your number at it.
#   TWILIO_NUMBER=+14155550123 ./scripts/local_tunnel.sh
set -euo pipefail
cd "$(dirname "$0")/.."
command -v ngrok >/dev/null || { echo "Install ngrok: https://ngrok.com/download"; exit 1; }
ngrok http 8080 --log=stdout >/tmp/ngrok.log 2>&1 &
sleep 4
URL="$(curl -s localhost:4040/api/tunnels | python3 -c 'import sys,json;print([t["public_url"] for t in json.load(sys.stdin)["tunnels"] if t["public_url"].startswith("https")][0])')"
echo "Tunnel: $URL"
echo "Set PUBLIC_BASE_URL=$URL in .env and restart the backend."
[[ -n "${TWILIO_NUMBER:-}" ]] && python3 scripts/setup_twilio.py --base-url "$URL" --number "$TWILIO_NUMBER"
wait
