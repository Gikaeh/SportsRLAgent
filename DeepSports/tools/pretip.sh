#!/usr/bin/env bash
# Light pre-tip job: `deepsports pretip` (NBA games tipping in the next 5-100 minutes: fresh ESPN
# injury report per game, then model v1.1i predictions for those games). Run by launchd at :20
# and :50 (tools/launchd/com.deepsports.pretip.plist); safe to run by hand. Skips quietly (exit
# 0) when another deepsports job holds the warehouse writer lock.
# Under launchd only uv's Python may read or write the drive (DECISIONS 2026-11-07): this script
# only tests that the file exists (a plain -e test is allowed) and leaves all access to deepsports.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

if [ ! -e data/deepsports.duckdb ]; then
  echo "$(ts) pretip: skipped, data dir unavailable (external drive not mounted?)"
  exit 0
fi
out=$(uv run deepsports pretip 2>&1)
status=$?
echo "$(ts) ${out//$'\n'/ | }"
exit $status
