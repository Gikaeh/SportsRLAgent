#!/usr/bin/env bash
# Evening book grab (watch-only forward test of opening-line totals): `deepsports books grab --early`
# writes tomorrow's night-before William Hill (Caesars feed) lines to
# <BOOKS_DIR>/williamhill/early/<date>.json; the day file the picks read is untouched.
# ~1 of OddsPapi's 250 free monthly requests. Run by launchd at 21:00
# (tools/launchd/com.deepsports.books-evening.plist); safe to run by hand. Non-fatal, capped at
# 2 min, one log line. Never needs the writer lock (one brief read-only open to match games).
# Under launchd only uv's Python may touch the drive (DECISIONS 2026-11-07): this script only
# tests that the warehouse file exists and leaves all access to deepsports.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

if [ ! -e data/deepsports.duckdb ]; then
  echo "$(ts) books early: skipped, data dir unavailable (external drive not mounted?)"
  exit 0
fi
raw=$(timeout -k 15 120 uv run --frozen deepsports books grab --early 2>/dev/null)
status=$?
out=$(printf '%s\n' "$raw" | tail -1)
if [ "$status" -eq 124 ] || [ "$status" -eq 137 ]; then out="timed out after 120 s"; fi
echo "$(ts) books grab --early: ${out:-no output} (exit $status)"

# The owner's night-before (opening) screenshots of tomorrow's games (the /circa page, "Tomorrow
# (opening)"): headless Claude reads them into <book>/lines/early/<date>.json. William Hill's go
# first because et-v1 uses them (screenshot lines win over the Caesars feed; pre-registration
# amendment 2026-11-16); Circa's are only recorded. Non-fatal, 5 min cap each.
early_read() {
  local book=$1 raw st out
  raw=$(timeout -k 15 300 uv run --frozen deepsports circa read --early --book "$book" 2>/dev/null)
  st=$?
  out=$(printf '%s\n' "$raw" | tail -1)
  if [ "$st" -eq 124 ] || [ "$st" -eq 137 ]; then out="timed out after 300 s"; fi
  echo "$(ts) $book early read: ${out:-no output} (exit $st)"
}
early_read williamhill

# Forward test et-v1 (docs/results/2026-11-15-early-totals-preregistration.md): log tomorrow's
# qualifying college totals at the night-before WH line (screenshots, else the Caesars feed). Watch-only, no stakes, append-only.
# Exit 3 = the warehouse was busy (a :15/:20 job): retry once after 3 minutes.
et_log() { timeout -k 15 180 uv run --frozen deepsports early-totals log 2>/dev/null | head -1; return "${PIPESTATUS[0]}"; }
et_out=$(et_log); et_status=$?
if [ "$et_status" -eq 3 ]; then
  sleep 180
  et_out=$(et_log); et_status=$?
fi
echo "$(ts) early-totals log: ${et_out:-no output} (exit $et_status)"

early_read circa

# Market context of tonight's et-v1 / et-v1-alt bets (opener, DraftKings at the bet line's time,
# Caesars feed, WH + Circa screenshots) to reports/early-totals/context.jsonl. Describe-only, its
# own process after the Circa read, so it can never change et-v1's files or exit code. Non-fatal.
cx_out=$(timeout -k 15 120 uv run --frozen deepsports early-totals context --log 2>/dev/null | tail -1)
echo "$(ts) early-totals context: ${cx_out:-no output}"

# To The Moon lotto card (watch-only; root docs/DECISIONS.md 2026-11-23, rule lotto-v2): tomorrow's
# et-v1 legs as a $1 top-7 test ticket + $0.25 7-leg spread tickets, logged once to
# reports/moon/lotto/cards.jsonl and sent to Discord. Reads files only. Non-fatal; nothing is sent on a night without a card.
lotto_msg=$(timeout -k 15 60 uv run --frozen deepsports moon lotto --format discord 2>/dev/null)
lotto_st=$?
echo "$(ts) moon lotto: $(printf '%s\n' "$lotto_msg" | head -1) (exit $lotto_st)"
if [ "$lotto_st" -eq 0 ] && printf '%s' "$lotto_msg" | grep -q "Test ticket"; then
  python3 "$HOME/.claude/tools/notify.py" --kind info "$lotto_msg" || true
fi

exit 0
