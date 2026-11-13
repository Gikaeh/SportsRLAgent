#!/usr/bin/env bash
# Daily models-only picks (watch-only): ManualBets export -> `deepsports model-picks run` -> Discord.
# Replaced the ensemble-agent vote on 2026-11-13 (DECISIONS). No Claude call: the rule is fixed
# (src/deepsports/analysis/model_picks.py). Called by tools/scheduled-sync.sh on the afternoon run;
# safe to run by hand.
#   MANUALBETS_EXPORT=<file>        reuse an export made earlier instead of running it
#   MANUALBETS_NBA_HOST=<ssh host>  where the NBA half runs (default rpi; read by manualbets-export.py)
#   PICKS_DAYS (default 1)          games tipping in the next N days
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
NOTIFY="python3 $HOME/.claude/tools/notify.py"
ts() { date '+%Y-%m-%d %H:%M:%S'; }
# Under launchd only uv's Python may touch the external drive (DECISIONS 2026-11-07).
PY="uv run --frozen python"

echo "=== $(ts) model picks start"

# ManualBets' view of the slate (edge 4). nba.com blocks this Mac's VPN, so the NBA half runs on
# the Pi. 2 Odds API credits (+3 for college). Capped at 20 min.
MB_JSON="$REPO/.sync/manualbets-export.json"
mkdir -p "$REPO/.sync" && rm -f "$MB_JSON"
if [ -n "${MANUALBETS_EXPORT:-}" ]; then
  cp "$MANUALBETS_EXPORT" "$MB_JSON" && mb_out="reused $MANUALBETS_EXPORT" || mb_out="couldn't copy $MANUALBETS_EXPORT"
else
  mb_out=$(timeout -k 30 1200 $PY tools/manualbets-export.py --out "$MB_JSON" 2>&1 | tail -1)
  mb_status=$?
  if [ "$mb_status" -eq 124 ] || [ "$mb_status" -eq 137 ]; then
    rm -f "$MB_JSON"  # may be half-written
    mb_out="timed out after 1200 s (exit $mb_status)"
  fi
fi
echo "$(ts) manualbets export: $mb_out"
if [ -s "$MB_JSON" ]; then MB_ARG="$MB_JSON"; else MB_ARG="none"; fi

# One retry after a minute (e.g. a writer briefly held the warehouse lock).
run_picks() { uv run --frozen deepsports model-picks run --days "${PICKS_DAYS:-1}" --manualbets "$MB_ARG"; }
if ! msg=$(run_picks); then
  echo "$(ts) model-picks failed; retrying in 60 s"
  sleep 60
  if ! msg=$(run_picks); then
    echo "$(ts) model-picks failed twice"
    $NOTIFY --kind blocked "DeepSports model picks skipped: the run failed twice. See ~/Library/Logs/DeepSports/sync.log" || true
    exit 1
  fi
fi
echo "$msg"
$NOTIFY --kind info "$msg" || true
echo "=== $(ts) model picks end"
