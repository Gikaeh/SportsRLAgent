#!/usr/bin/env bash
# launchd entry point for the BetDesk pusher (com.betdesk.pusher, every 60 s).
# Reads secrets from the login Keychain (service "betdesk"; see docs/SETUP.md) and the Worker URL
# from ~/.config/betdesk/env, then runs one push. Secrets never touch files or the repo.
set -euo pipefail
cd "$(dirname "$0")/.."
CONF="$HOME/.config/betdesk/env"   # holds BETDESK_URL=https://betdesk.<subdomain>.workers.dev (not a secret)
[ -f "$CONF" ] && . "$CONF"
: "${BETDESK_URL:?set BETDESK_URL in $CONF}"
kc() { security find-generic-password -s betdesk -a "$1" -w 2>/dev/null || { echo "push: FAILED, Keychain item betdesk/$1 missing" >&2; exit 2; }; }
BETDESK_INGEST_TOKEN="$(kc ingest-token)"
CF_ACCESS_CLIENT_ID="$(kc access-client-id)"
CF_ACCESS_CLIENT_SECRET="$(kc access-client-secret)"
export BETDESK_URL BETDESK_INGEST_TOKEN CF_ACCESS_CLIENT_ID CF_ACCESS_CLIENT_SECRET
printf '%s ' "$(date '+%F %T')"
exec "${NODE:-node}" --experimental-strip-types --disable-warning=ExperimentalWarning pusher/src/push.ts "$@"
