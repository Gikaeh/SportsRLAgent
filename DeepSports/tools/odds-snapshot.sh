#!/usr/bin/env bash
# Frequent pregame line capture: `deepsports odds-snapshot` (today + tomorrow, NBA + college,
# pregame odds rows only). Run by launchd every 30 minutes
# (tools/launchd/com.deepsports.odds.plist); safe to run by hand. Skips quietly (exit 0) when
# another deepsports job holds the warehouse writer lock.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

if [ ! -e data/deepsports.duckdb ]; then
  echo "$(ts) odds-snapshot: skipped, data dir unavailable (external drive not mounted?)"
  exit 0
fi
out=$(uv run deepsports odds-snapshot 2>&1)
status=$?
echo "$(ts) ${out//$'\n'/ | }"
exit $status
