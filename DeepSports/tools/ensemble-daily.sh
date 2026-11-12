#!/usr/bin/env bash
# Daily ensemble-betting vote (watch-only): slate -> N independent bettor agents -> majority -> Discord.
# Called by tools/scheduled-sync.sh on the afternoon run; safe to run by hand.
#   ENSEMBLE_AGENTS (default 10)  number of bettors. A one-day override without touching launchd:
#                                 put a number 1-30 in .sync/ensemble-agents.<YYYY-MM-DD> (used that
#                                 day only; anything else is ignored and the default is used).
#   ENSEMBLE_TIMEOUT (default 3000) hard limit in seconds for the whole claude call (all bettors).
#   ENSEMBLE_DAYS   (default 1)   window: games tipping 1 h .. N days from now. With one run a day
#                                 and N=1, consecutive runs never vote on the same game.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
# Long-lived token for headless `claude -p` (from `claude setup-token`), kept outside the repo.
TOKEN_FILE="$HOME/.config/deepsports/claude-oauth-token"
[ -r "$TOKEN_FILE" ] && export CLAUDE_CODE_OAUTH_TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"
NOTIFY="python3 $HOME/.claude/tools/notify.py"
ts() { date '+%Y-%m-%d %H:%M:%S'; }
AGENTS_DEFAULT=10
OVERRIDE_FILE="$REPO/.sync/ensemble-agents.$(date +%F)"
if [ -z "${ENSEMBLE_AGENTS:-}" ] && [ -s "$OVERRIDE_FILE" ]; then
  IFS=$' \t\r' read -r override < "$OVERRIDE_FILE" || true  # first line, ends trimmed
  if [[ "$override" =~ ^[0-9]+$ ]] && [ "${#override}" -le 9 ] && [ "$((10#$override))" -ge 1 ] && [ "$((10#$override))" -le 30 ]; then
    AGENTS_DEFAULT=$((10#$override))
    echo "$(ts) one-day override: $AGENTS_DEFAULT agents ($OVERRIDE_FILE)"
  else
    echo "$(ts) ignoring override '$(head -c 40 "$OVERRIDE_FILE" | tr -d '\n')' in $OVERRIDE_FILE (want a number 1-30); using $AGENTS_DEFAULT"
  fi
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
# vote still runs and the context says the ManualBets facts are missing. Capped at 20 min
# (a hung ssh or nba.com call must not eat the bettors' time).
#   MANUALBETS_EXPORT=<file>  reuse an export made earlier instead
#   MANUALBETS_NBA_HOST=<ssh host>  where the NBA half runs (default rpi; empty = this Mac)
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

# +tools1: bettors may research (read API, ManualBets files, web), so grade keeps these runs apart.
# One retry after a minute (e.g. a writer briefly held the warehouse lock).
make_context() {
  uv run deepsports ensemble-bets context --agents "$AGENTS" --days "$DAYS" --manualbets "$MB_ARG" \
    --tag "+tools1"
}
if ! out=$(make_context); then
  echo "$(ts) ensemble context failed; retrying in 60 s"
  sleep 60
  if ! out=$(make_context); then
    echo "$(ts) ensemble context failed twice; no vote today"
    $NOTIFY --kind blocked "DeepSports ensemble vote skipped: building the context failed twice. See ~/Library/Logs/DeepSports/sync.log" || true
    exit 1
  fi
fi
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
rm -rf "$WORK" && mkdir -p "$WORK/replies"
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
# bettors' picks or earlier runs (independence). Replies are saved to $WORK/replies/ only after every
# bettor has finished, so that folder needs no deny rule. It must not have one: a Read deny on a path
# also blocks Write there, which stopped the coordinator from saving any reply on 2026-11-12.
# Hard limit so a hung bettor can't block the rest of the sync; JSON output gives cost and duration.
CLAUDE_OUT="$REPO/.sync/ensemble-claude.json"
rm -f "$CLAUDE_OUT"
timeout -k 60 "${ENSEMBLE_TIMEOUT:-3000}" \
claude -p "/ensemble-betting prefetched $WORK $AGENTS" --model sonnet --output-format json \
  --add-dir "$REPO/../ManualBets" \
  --allowedTools "Read" "Write" "Agent" "Skill" "ToolSearch" "Grep" "Glob" "WebSearch" "WebFetch" \
    "Bash(curl -s http://localhost:8787/*)" "Bash(curl -s 'http://localhost:8787/*)" \
    "Bash(curl -s \"http://localhost:8787/*)" \
  --disallowedTools "Read(//Volumes/ExFATStorag/DeepSports/reports/**)" \
    "Read(./.sync/ensemble-sim/**)" "Read(~/Library/Logs/DeepSports/**)" > "$CLAUDE_OUT"
status=$?
REPLIES=$(ls "$WORK"/replies/picks-*.json 2>/dev/null | wc -l | tr -d ' ')
[ "$status" -eq 124 ] && echo "$(ts) claude timed out after ${ENSEMBLE_TIMEOUT:-3000} s"
python3 - "$CLAUDE_OUT" <<'PY' || true
import json, sys
try:
    r = json.load(open(sys.argv[1]))
except (OSError, ValueError):
    print("claude: no JSON result (killed or failed)")
else:
    cost, ms = r.get("total_cost_usd"), r.get("duration_ms")
    print("claude: {}; cost ${}; {:.1f} min".format(
        "error" if r.get("is_error") else "ok",
        "?" if cost is None else f"{cost:.2f}", (ms or 0) / 60000))
    print((r.get("result") or "").strip()[:2000])
PY
echo "$(ts) claude exit $status; $REPLIES of $AGENTS replies"
if [ "$REPLIES" -eq 0 ]; then
  # Leave the run untallied: a tally would freeze it as "no majority" and grade would count it.
  why="claude exit $status"; [ "$status" -eq 124 ] && why="timed out after ${ENSEMBLE_TIMEOUT:-3000} s"
  $NOTIFY --kind blocked "DeepSports ensemble vote failed: 0 of $AGENTS bettors replied ($why). Run left untallied: $RUN. See ~/Library/Logs/DeepSports/sync.log" || true
  exit 1
fi

copied=$(copy_matching "$WORK/replies/picks-*.json" "$RUN")
if [ "${copied:-0}" != "$REPLIES" ]; then
  # A tally would freeze the run without the missing picks; leave it for a manual tally.
  echo "$(ts) copied ${copied:-0} of $REPLIES picks to $RUN; run left untallied"
  $NOTIFY --kind blocked "DeepSports ensemble vote: copied ${copied:-0} of $REPLIES picks to the drive; run left untallied: $RUN. See ~/Library/Logs/DeepSports/sync.log" || true
  exit 1
fi
if ! tally=$(uv run deepsports ensemble-bets tally "$RUN"); then
  echo "$(ts) tally failed"
  $NOTIFY --kind blocked "DeepSports ensemble vote: tally failed. See ~/Library/Logs/DeepSports/sync.log" || true
  exit 1
fi
# The record for this run's context version only (versions differ in what bettors could see).
record=$(uv run deepsports ensemble-bets grade | $PY -c '
import json, sys
ver = json.load(open(sys.argv[1]))["context_version"]
g = json.load(sys.stdin)["by_context_version"].get(ver, {}).get("majority") or {}
if g.get("bets"):
    print("Record for {}: {} (W-L-P) over {} majority picks, {:+} units".format(ver, g["record"], g["bets"], g["units_profit"]))
else:
    print("No graded majority picks yet for {}.".format(ver))' "$RUN/tally.json") || record="(record unavailable)"

# Discord: the majority picks as a table, plus close calls (the full tally stays in the run dir).
summary=$(uv run deepsports ensemble-bets table "$RUN") || summary="(table failed; see $RUN/tally.md)"
replied=""
[ "$REPLIES" -lt "$AGENTS" ] && replied="
Only $REPLIES of $AGENTS bettors replied; the rest count as passes, so a majority still needs more than $((AGENTS / 2))."
$NOTIFY --kind info "Ensemble vote: what to bet ($AGENTS bettors, $GAMES games, NBA + college, watch-only)$replied
$summary
$record
Run: $RUN" || true
echo "$tally"
echo "=== $(ts) ensemble vote end"
