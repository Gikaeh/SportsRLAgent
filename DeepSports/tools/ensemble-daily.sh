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

echo "=== $(ts) ensemble vote start (agents $AGENTS, days $DAYS)"
out=$(uv run deepsports ensemble-bets context --agents "$AGENTS" --days "$DAYS") || {
  echo "$(ts) ensemble context failed"; exit 1; }
RUN=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["run"])' <<<"$out")
GAMES=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["games"])' <<<"$out")
echo "$(ts) run $RUN, $GAMES bettable games"
if [ "$GAMES" -eq 0 ]; then
  echo "$(ts) no bettable games; skipping the vote"
  rm -rf "$RUN"
  exit 0
fi

# Headless Claude works on a copy inside the repo (its sandbox is unreliable on the external drive).
WORK="$REPO/.sync/ensemble"
rm -rf "$WORK" && mkdir -p "$WORK"
cp "$RUN"/context-*.md "$WORK"/

# Sonnet coordinates (it only launches bettors and saves replies); bettors are Sonnet too.
claude -p "/ensemble-betting prefetched $WORK $AGENTS" --model sonnet \
  --allowedTools "Read" "Write" "Agent" "Skill" "ToolSearch"
status=$?
echo "$(ts) claude exit $status; $(ls "$WORK"/picks-*.json 2>/dev/null | wc -l | tr -d ' ') of $AGENTS replies"

cp "$WORK"/picks-*.json "$RUN"/ 2>/dev/null || true
if ! tally=$(uv run deepsports ensemble-bets tally "$RUN"); then
  echo "$(ts) tally failed"
  $NOTIFY --kind blocked "DeepSports ensemble vote: tally failed. See ~/Library/Logs/DeepSports/sync.log" || true
  exit 1
fi
record=$(uv run deepsports ensemble-bets grade | python3 -c '
import json, sys
g = json.load(sys.stdin)["majority"]
print(f"Majority record so far: {g[\"record\"]} (W-L-P), {g[\"units_profit\"]:+} units" if g["bets"] else "No graded majority picks yet.")')

# Discord: the majority section only (the full tally stays in the run dir).
summary=$(python3 - "$RUN/tally.md" <<'PY'
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
