#!/usr/bin/env bash
# Daily ensemble-betting vote (watch-only): slate -> N independent bettor agents -> majority -> Discord.
# Called by tools/scheduled-sync.sh on the afternoon run; safe to run by hand.
#   ENSEMBLE_AGENTS (default 10)  number of bettors. A one-day override without touching launchd:
#                                 put a number in .sync/ensemble-agents.<YYYY-MM-DD> (used that day only).
#   ENSEMBLE_DAYS   (default 1)   window: games tipping 1 h .. N days from now. With one run a day
#                                 and N=1, consecutive runs never vote on the same game.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
NOTIFY="python3 $HOME/.claude/tools/notify.py"
ts() { date '+%Y-%m-%d %H:%M:%S'; }
AGENTS_DEFAULT=10
OVERRIDE_FILE="$REPO/.sync/ensemble-agents.$(date +%F)"
if [ -z "${ENSEMBLE_AGENTS:-}" ] && [ -s "$OVERRIDE_FILE" ]; then
  AGENTS_DEFAULT=$(tr -dc '0-9' < "$OVERRIDE_FILE")
  echo "$(ts) one-day override: $AGENTS_DEFAULT agents ($OVERRIDE_FILE)"
fi
AGENTS="${ENSEMBLE_AGENTS:-$AGENTS_DEFAULT}"
DAYS="${ENSEMBLE_DAYS:-1}"

# Under launchd, macOS only lets uv's Python touch the external drive: bash globs, cp, rm and the
# system python3 get "Operation not permitted" there. So every file operation on $RUN goes through
# $PY (DECISIONS 2026-11-07). It's also Python 3.12; the system python3 is 3.9.
PY="uv run python"
# copy_matching <glob> <dest dir>: copies the matches, prints how many there were.
copy_matching() {
  $PY -c '
import glob, os, shutil, sys
files = glob.glob(sys.argv[1])
for f in files:
    shutil.copyfile(f, os.path.join(sys.argv[2], os.path.basename(f)))
print(len(files))' "$1" "$2"
}

echo "=== $(ts) ensemble vote start (agents $AGENTS, days $DAYS)"

# ManualBets' view of the slate (its XGBoost models, Kelly picks, best Odds API prices) goes into
# every context file (root AGENTS.md: betting analysis uses all the repo's tools; edge 4). nba.com
# blocks this Mac's NordVPN, so tools/manualbets-export.py runs the NBA half on the Pi (ssh `rpi`)
# and college here. 2 Odds API credits (+3 for college once teams have 5 games). On failure the
# vote still runs and the context says the ManualBets facts are missing.
#   MANUALBETS_EXPORT=<file>  reuse an export made earlier instead
#   MANUALBETS_NBA_HOST=<ssh host>  where the NBA half runs (default rpi; empty = this Mac)
MB_JSON="$REPO/.sync/manualbets-export.json"
mkdir -p "$REPO/.sync" && rm -f "$MB_JSON"
if [ -n "${MANUALBETS_EXPORT:-}" ]; then
  cp "$MANUALBETS_EXPORT" "$MB_JSON" && mb_out="reused $MANUALBETS_EXPORT" || mb_out="couldn't copy $MANUALBETS_EXPORT"
else
  mb_out=$($PY tools/manualbets-export.py --out "$MB_JSON" 2>&1 | tail -1)
fi
echo "$(ts) manualbets export: $mb_out"
if [ -s "$MB_JSON" ]; then MB_ARG="$MB_JSON"; else MB_ARG="none"; fi

# +tools1: bettors may research (read API, ManualBets files, web), so grade keeps these runs apart.
out=$(uv run deepsports ensemble-bets context --agents "$AGENTS" --days "$DAYS" --manualbets "$MB_ARG" \
  --tag "+tools1") || {
  echo "$(ts) ensemble context failed"; exit 1; }
RUN=$($PY -c 'import json,sys; print(json.load(sys.stdin)["run"])' <<<"$out")
GAMES=$($PY -c 'import json,sys; print(json.load(sys.stdin)["games"])' <<<"$out")
echo "$(ts) run $RUN, $GAMES bettable games"
if [ "$GAMES" -eq 0 ]; then
  echo "$(ts) no bettable games; skipping the vote"
  $PY -c 'import shutil,sys; shutil.rmtree(sys.argv[1])' "$RUN"
  exit 0
fi

# Headless Claude works on a copy inside the repo (its sandbox is unreliable on the external drive).
WORK="$REPO/.sync/ensemble"
rm -rf "$WORK" && mkdir -p "$WORK"
copied=$(copy_matching "$RUN/context-*.md" "$WORK")
if [ "${copied:-0}" -ne "$AGENTS" ]; then
  # Don't launch bettors with nothing to read.
  echo "$(ts) copied ${copied:-0} of $AGENTS context files; skipping the vote"
  $NOTIFY --kind blocked "DeepSports ensemble vote skipped: copied ${copied:-0} of $AGENTS context files. See ~/Library/Logs/DeepSports/sync.log" || true
  exit 1
fi

# Sonnet coordinates (it only launches bettors and saves replies); bettors are Sonnet too.
# Bettors may research: read files (incl. ManualBets), the DeepSports read API via curl, and the web.
# No other shell commands (one DuckDB writer; no Odds API calls per bettor), and no reading other
# bettors' picks or earlier runs (independence).
claude -p "/ensemble-betting prefetched $WORK $AGENTS" --model sonnet \
  --add-dir "$REPO/../ManualBets" \
  --allowedTools "Read" "Write" "Agent" "Skill" "ToolSearch" "Grep" "Glob" "WebSearch" "WebFetch" \
    "Bash(curl -s http://localhost:8787/*)" "Bash(curl -s 'http://localhost:8787/*)" \
    "Bash(curl -s \"http://localhost:8787/*)" \
  --disallowedTools "Read(//Volumes/ExFATStorag/DeepSports/reports/**)" "Read(./.sync/ensemble/picks-*)"
status=$?
echo "$(ts) claude exit $status; $(ls "$WORK"/picks-*.json 2>/dev/null | wc -l | tr -d ' ') of $AGENTS replies"

copy_matching "$WORK/picks-*.json" "$RUN" >/dev/null || echo "$(ts) couldn't copy picks to $RUN"
if ! tally=$(uv run deepsports ensemble-bets tally "$RUN"); then
  echo "$(ts) tally failed"
  $NOTIFY --kind blocked "DeepSports ensemble vote: tally failed. See ~/Library/Logs/DeepSports/sync.log" || true
  exit 1
fi
record=$(uv run deepsports ensemble-bets grade | $PY -c '
import json, sys
g = json.load(sys.stdin)["majority"]
print("Majority record so far: {} (W-L-P), {:+} units".format(g["record"], g["units_profit"]) if g["bets"] else "No graded majority picks yet.")')

# Discord: the majority picks as a table, plus close calls (the full tally stays in the run dir).
summary=$(uv run deepsports ensemble-bets table "$RUN") || summary="(table failed; see $RUN/tally.md)"
$NOTIFY --kind info "Ensemble vote: what to bet ($AGENTS bettors, $GAMES games, NBA + college, watch-only)
$summary
$record
Run: $RUN" || true
echo "$tally"
echo "=== $(ts) ensemble vote end"
