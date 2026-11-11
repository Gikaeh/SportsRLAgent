#!/usr/bin/env bash
# Daily ensemble-betting vote (watch-only): slate -> N independent bettor agents -> majority -> Discord.
# Called by tools/scheduled-sync.sh on the afternoon run; safe to run by hand.
#   ENSEMBLE_AGENTS (default 10)  number of bettors
#   ENSEMBLE_DAYS   (default 1)   window: games tipping 1 h .. N days from now. With one run a day
#                                 and N=1, consecutive runs never vote on the same game.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
NOTIFY="python3 $HOME/.claude/tools/notify.py"
ts() { date '+%Y-%m-%d %H:%M:%S'; }
AGENTS="${ENSEMBLE_AGENTS:-10}"
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

out=$(uv run deepsports ensemble-bets context --agents "$AGENTS" --days "$DAYS" --manualbets "$MB_ARG") || {
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
claude -p "/ensemble-betting prefetched $WORK $AGENTS" --model sonnet \
  --allowedTools "Read" "Write" "Agent" "Skill" "ToolSearch"
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

# Discord: the majority section only (the full tally stays in the run dir).
summary=$($PY - "$RUN/tally.md" <<'PY'
import sys
lines = open(sys.argv[1]).read().splitlines()
keep, on = [], False
for ln in lines:
    if ln.startswith("## Majority"):
        on = True
    elif ln.startswith("## ") and on:
        break
    if on and not ln.startswith("  - "):  # drop per-agent reasons to stay phone-sized
        keep.append(ln.replace("## ", ""))
print("\n".join(keep))
PY
)
$NOTIFY --kind info "Ensemble vote ($AGENTS bettors, $GAMES games, watch-only)
$summary
$record
Run: $RUN" || true
echo "$tally"
echo "=== $(ts) ensemble vote end"
