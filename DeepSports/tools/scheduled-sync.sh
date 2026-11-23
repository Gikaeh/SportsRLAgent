#!/usr/bin/env bash
# Scheduled refresh: update the warehouse, predict, paper log; afternoon run adds the model picks.
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

# Venue geography (offline, ~20 s): geocode venues new to `games` (neutral sites, new arenas)
# into the venues table from the GeoNames files on the drive. Non-fatal; capped at 5 min.
if ! timeout -k 15 300 uv run deepsports venues build; then
  echo "$(ts) venues build reported errors (continuing)"
fi

# Opening lines (ESPN core API, 1 request per game) for games that went final in the last 4 days
# and have no opening row yet. Core responses are cached forever, so a game ESPN has no opening
# line for costs a cache read, not a request, on later runs. Non-fatal; capped at 300 games / 15 min.
for league in nba ncaab; do
  if ! timeout -k 15 900 uv run deepsports odds-history --league "$league" --with-opening --days 4 --limit 300; then
    echo "$(ts) odds-history --league $league (opening lines) reported errors (continuing)"
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
# Watch-only altitude shadow ncaab-v1.1alt (ncaab-v1 + venue altitude in the total model; DECISIONS
# 2026-11-22): hidden like ncaab-v1p, read only by the 21:00 et-v1-alt shadow log. Needs the venues
# table (venues build above); failure is non-fatal and never touches ncaab-v1.
if ! uv run deepsports predict --league ncaab --model-version ncaab-v1.1alt; then
  echo "$(ts) predict --league ncaab ncaab-v1.1alt (altitude shadow) reported errors (continuing)"
fi

# Forward paper-trade log (watch-only, no money): the frozen rules in analysis/paper.py log
# today's qualifying bets from the predictions above and the latest pregame lines. Insert-only.
if ! uv run deepsports paper log; then
  echo "$(ts) paper log reported errors (continuing)"
fi

# Calendar sync scrapped for now (owner, 2026-11-13; DECISIONS). The skill and `deepsports upcoming`
# stay; nothing here calls Claude any more.
status=0
# Models-only picks (watch-only; replaced the ensemble-agent vote 2026-11-13), once a day:
# weekdays on the 14:00 run; Saturday and Sunday on the 08:00 run instead, since weekend games tip
# from ~9 AM and Circa posts the day's college lines ~7 AM (owner, 2026-11-14). Once a day keeps one
# picks run and one moon proposal per day. Non-fatal; posts its own Discord message.
# The vote can still be run by hand: tools/ensemble-daily.sh.
hour=$((10#$(date +%H)))
dow=$(date +%u)  # 6 = Saturday, 7 = Sunday
if [ "$dow" -ge 6 ]; then picks_now=$([ "$hour" -lt 12 ] && echo 1 || echo 0)
else picks_now=$([ "$hour" -ge 12 ] && echo 1 || echo 0); fi
if [ "$picks_now" = 1 ] && [ "${SKIP_PICKS:-0}" != 1 ]; then
  "$REPO/tools/model-picks-daily.sh" || echo "$(ts) model picks failed (exit $?)"
fi
echo "=== $(ts) scheduled sync end"
exit $status
