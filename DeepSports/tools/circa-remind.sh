#!/usr/bin/env bash
# Circa screenshot reminder (launchd com.deepsports.circa-remind, 11:00 and 13:00 local): ingest the
# iCloud inbox, then if today has no screenshots, ask the owner on Discord to upload some before
# the 14:00 picks. Silent otherwise. Never touches DuckDB. Safe to run by hand.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
NOTIFY="python3 $HOME/.claude/tools/notify.py"
ts() { date '+%Y-%m-%d %H:%M:%S'; }
# Only uv's Python may touch the external drive under launchd, so every file step goes through it.

ingest=$(timeout -k 15 120 uv run --frozen deepsports circa ingest 2>&1 | tail -1)
echo "$(ts) circa ingest: $ingest"
count=$(timeout -k 15 60 uv run --frozen deepsports circa status --json 2>/dev/null \
  | uv run --frozen python -c 'import json,sys; print(json.load(sys.stdin)["count"])' 2>/dev/null)
if ! [[ "${count:-}" =~ ^[0-9]+$ ]]; then
  echo "$(ts) circa status unavailable (external drive?); no reminder"
  exit 0
fi
echo "$(ts) circa screenshots today: $count"
if [ "$count" -eq 0 ]; then
  msg="Upload today's Circa screenshots before the 2 PM picks (on home Wi-Fi: http://<mac>:8787/circa, or BetDesk > Circa)"
  case "$ingest" in
    "inbox blocked"*) msg="$msg. Note: this Mac couldn't read the iCloud folder (macOS permission; see docs/PIPELINE.md, Circa)." ;;
  esac
  $NOTIFY --kind input "$msg" || true
fi
exit 0
