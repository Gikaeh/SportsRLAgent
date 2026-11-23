#!/usr/bin/env bash
# Scheduled live line capture from The Odds API (the owner's key, ~41.6K credits until about
# 2026-12-23): `deepsports odds-api-history live` saves college + NBA totals/spreads from 10 books
# (2 credits per league per run; every upcoming event, next-day games included) to
# RAW_DIR/oddsapi/live/<sport>/<UTC slot>.json.gz. Run by launchd at 09:00 and every 30 min
# 12:00-21:30 (tools/launchd/com.deepsports.oddsapi-live.plist); safe to run by hand (a saved slot
# is skipped). Files only: never a warehouse writer. Non-fatal, capped at 2 min, one log line. The
# command itself stops after --until, under --reserve, and without a working key.
# At the 18:30, 19:00 and 19:30 slots it then runs `deepsports momentum-freeze` (momentum forward
# test, pre-registered 2026-11-23): tomorrow's college DS predictions (one read-only open) and a
# copy of the ManualBets export, write-once under REPORTS_DIR/momentum-forward/frozen/<D>/<HHMM>/.
# Non-fatal, capped at 3 min, one log line.
# Under launchd only uv's Python may touch the drive (DECISIONS 2026-11-07): this script does not
# test or read anything under data/ or the reports folder.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

raw=$(timeout -k 15 120 uv run --frozen deepsports odds-api-history live 2>/dev/null)
status=$?
out=$(printf '%s\n' "$raw" | tail -1)
if [ "$status" -eq 124 ] || [ "$status" -eq 137 ]; then out="timed out after 120 s"; fi
echo "$(ts) ${out:-oddsapi live: no output} (exit $status)"

# Local (Pacific) 30-min slot of this run, e.g. 1900.
hh=$(date '+%H'); mm=$(date '+%M')
if [ "$((10#$mm))" -lt 30 ]; then slot="${hh}00"; else slot="${hh}30"; fi
case "$slot" in
  1830|1900|1930)
    fzraw=$(timeout -k 15 180 uv run --frozen deepsports momentum-freeze --slot "$slot" 2>/dev/null)
    fst=$?
    fz=$(printf '%s\n' "$fzraw" | tail -1)
    if [ "$fst" -eq 124 ] || [ "$fst" -eq 137 ]; then fz="momentum freeze: timed out after 180 s"; fi
    echo "$(ts) ${fz:-momentum freeze: no output} (exit $fst)"
    ;;
esac
exit 0
