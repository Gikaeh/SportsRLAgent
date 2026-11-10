#!/usr/bin/env bash
# Scheduled refresh: update the warehouse, then let Claude reconcile Google Calendar.
# Run by launchd (tools/launchd/com.deepsports.sync.plist); safe to run by hand.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
NOTIFY="python3 $HOME/.claude/tools/notify.py --kind blocked"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

echo "=== $(ts) scheduled sync start"
if [ ! -e data/deepsports.duckdb ]; then
  echo "$(ts) data dir unavailable (external drive not mounted?)"
  $NOTIFY "DeepSports scheduled sync skipped: external drive ExFATStorag not mounted." || true
  exit 2
fi

# Preflight: can this launchd job actually open the warehouse? On 2026-11-08 (macOS update pending)
# the file existed but every open failed with "Operation not permitted", and the run went through
# every step failing. Retry a few times (the drive may be waking), then alert and stop.
# Uses uv's Python: under launchd only it may touch the drive (DECISIONS 2026-11-07).
preflight() {
  uv run python -c '
from deepsports.store import Store
Store(read_only=True, lock_wait=120).close()' 2>&1 | tail -1
  return "${PIPESTATUS[0]}"
}
ok=0
for attempt in 1 2 3; do
  if err=$(preflight); then ok=1; break; fi
  echo "$(ts) preflight $attempt/3: cannot open the warehouse: $err"
  [ "$attempt" -lt 3 ] && sleep 60
done
if [ "$ok" -ne 1 ]; then
  $NOTIFY "DeepSports scheduled sync stopped: can't open the warehouse ($err). If this persists, restart the Mac or check Privacy & Security > Files & Folders / Removable Volumes. See ~/Library/Logs/DeepSports/sync.log" || true
  exit 4
fi

for league in nba ncaab; do
  if ! uv run deepsports update --league "$league"; then
    echo "$(ts) update --league $league reported errors (continuing)"
  fi
done

# Model v1 predictions for upcoming NBA and college games (pre-tip only); the calendar skill reads them
# through `deepsports upcoming --json`.
# v1.0, v1.1 and v1.1i are all kept and graded so their records can be compared. v1.1i (v1.1 +
# pre-tip injury reports) only covers games with a captured report (update above takes them for
# the next 2 days); `deepsports pretip` (launchd :20/:50) refreshes it shortly before tip. The
# calendar never shows v1.1i (config.CALENDAR_EXCLUDED_VERSIONS), so it keeps v1.1 even though
# v1.1i is written last; the API prefers v1.1i, then v1.1 (DECISIONS 2026-11-10).
for version in v1.0 v1.1 v1.1i; do
  if ! uv run deepsports predict --model-version "$version"; then
    echo "$(ts) predict $version reported errors (continuing)"
  fi
done
# College v1 (D1-vs-D1 games where both teams have >= 5 games this season; none early on).
if ! uv run deepsports predict --league ncaab --model-version ncaab-v1; then
  echo "$(ts) predict --league ncaab reported errors (continuing)"
fi
# College prior model (cross-season prior, DECISIONS 2026-11-06), fit once for two versions:
# ncaab-v1p (same >= 5 games gate, graded beside ncaab-v1, never displayed) and the opt-in
# ncaab-v1-early (teams with >= 1 game; hidden in the apps unless turned on, never on the calendar).
# Runs after ncaab-v1; the calendar and cards skip ncaab-v1p regardless of write order.
if ! uv run deepsports predict --league ncaab --model-version ncaab-v1p,ncaab-v1-early; then
  echo "$(ts) predict --league ncaab prior model (v1p, early) reported errors (continuing)"
fi

# Forward paper-trade log (watch-only, no money): the frozen rules in analysis/paper.py log
# today's qualifying bets from the predictions above and the latest pregame lines. Insert-only.
if ! uv run deepsports paper log; then
  echo "$(ts) paper log reported errors (continuing)"
fi

# Export the games to sync. Headless Claude's Bash sandbox can't open the DuckDB file on the
# external drive (it hangs), so Claude only reads these files and talks to Google Calendar.
SYNC_DIR="$REPO/.sync"
mkdir -p "$SYNC_DIR"
rm -f "$SYNC_DIR"/upcoming*.json
if ! uv run deepsports upcoming --league all --json > "$SYNC_DIR/upcoming.json.tmp"; then
  echo "$(ts) upcoming export failed; skipping calendar sync"
  $NOTIFY "DeepSports calendar sync skipped: couldn't export upcoming games. See ~/Library/Logs/DeepSports/sync.log" || true
  exit 3
fi
mv "$SYNC_DIR/upcoming.json.tmp" "$SYNC_DIR/upcoming.json"
for league in nba ncaab; do
  uv run deepsports upcoming --league "$league" --all --days 30 --json \
    > "$SYNC_DIR/upcoming-30d-$league.json" || rm -f "$SYNC_DIR/upcoming-30d-$league.json"
done

# Headless Claude runs the calendar skill with only the tools it needs.
# Its Stop hook posts the summary to Discord.
claude -p "/sync-game-calendar prefetched $SYNC_DIR" \
  --allowedTools \
    "Read" "Skill" "ToolSearch" \
    "mcp__claude_ai_Google_Calendar__list_events" \
    "mcp__claude_ai_Google_Calendar__create_event" \
    "mcp__claude_ai_Google_Calendar__update_event" \
    "mcp__claude_ai_Google_Calendar__delete_event"
status=$?
if [ $status -ne 0 ]; then
  $NOTIFY "DeepSports calendar sync failed (claude exit $status). See ~/Library/Logs/DeepSports/sync.log" || true
fi
# Afternoon run only: the daily ensemble-betting vote (watch-only). Non-fatal; posts its own summary.
if [ "$(date +%H)" -ge 12 ] && [ "${SKIP_ENSEMBLE:-0}" != 1 ]; then
  "$REPO/tools/ensemble-daily.sh" || echo "$(ts) ensemble vote failed (exit $?)"
fi
echo "=== $(ts) scheduled sync end (claude exit $status)"
exit $status
