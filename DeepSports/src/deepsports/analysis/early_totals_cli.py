"""`deepsports early-totals log|grade|status`: the `et-v1` night-before college totals forward test.

Watch-only (never places or sizes a bet). Rule and pass/fail are pre-registered in
docs/results/2026-11-15-early-totals-preregistration.md; logic in `analysis/early_totals.py`.

Files under `<REPORTS_DIR>/early-totals/` (append-only, no stakes):
- `bets.jsonl`: one row per qualifying bet; the first row per (rule version, game) is the bet.
- `runs.jsonl`: one row per `log` run (also nights with no bet, missing inputs or a busy warehouse).
- `grade.json`: the latest `grade` output (derived; rewritten each time).

The warehouse is opened read-only with a short lock wait; if a writer holds it the command prints
one line and exits 3 without logging a bet.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from deepsports import config
from deepsports.analysis import early_totals as et

OUT_DIR = config.REPORTS_DIR / "early-totals"
MB_EXPORT = config.ROOT / ".sync" / "manualbets-export.json"
BUSY_EXIT = 3


def _paths(out_dir: Path) -> dict[str, Path]:
    return {k: out_dir / f for k, f in (("bets", "bets.jsonl"), ("runs", "runs.jsonl"),
                                        ("grade", "grade.json"), ("lock", ".lock"))}  # fmt: skip


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue  # a torn last line from a crash: ignored, never rewritten
    return out


def append_jsonl(path: Path, rows: Sequence[dict]) -> None:
    if not rows:
        return
    with path.open("a") as f:
        for r in rows:
            f.write(json.dumps(r, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())


# ---------- inputs ----------


def load_early_lines(game_date: date) -> dict | None:
    """The night-before Caesars file for the game day (`books.grab.load_early`, named after the
    game day); the caller keeps only that day's games."""
    from deepsports.books import grab

    return grab.load_early(et.BOOK, game_date)


GAMES_SQL = """
SELECT g.game_id, g.start_time_utc, h.abbreviation AS home, a.abbreviation AS away
FROM games g
JOIN teams h ON h.league = g.league AND h.team_id = g.home_team_id
JOIN teams a ON a.league = g.league AND a.team_id = g.away_team_id
WHERE g.league = 'ncaab' AND g.state = 'pre' AND g.season_type IN (2, 3)
  AND CAST(timezone(?, g.start_time_utc) AS DATE) = ?
ORDER BY g.start_time_utc, g.game_id
"""

REST_SQL = """
WITH tg AS (
  SELECT game_id, start_time_utc, home_team_id AS team FROM games WHERE league = 'ncaab'
  UNION ALL
  SELECT game_id, start_time_utc, away_team_id FROM games WHERE league = 'ncaab'
), lagged AS (
  SELECT game_id, start_time_utc,
         lag(start_time_utc) OVER (PARTITION BY team ORDER BY start_time_utc) AS prev
  FROM tg
)
SELECT game_id, min(date_diff('second', prev, start_time_utc)) / 86400.0
FROM lagged WHERE game_id IN ({ids}) GROUP BY 1
"""


def load_games(con: duckdb.DuckDBPyConnection, game_date: date) -> list[dict[str, Any]]:
    rows = con.execute(GAMES_SQL, [config.LOCAL_TZ.key, game_date]).fetchall()
    games = [{"game_id": g, "start_time_utc": s, "home": h, "away": a} for g, s, h, a in rows]
    if games:
        ids = [g["game_id"] for g in games]
        sql = REST_SQL.format(ids=", ".join("?" for _ in ids))
        rest = dict(con.execute(sql, ids).fetchall())
        for g in games:
            r = rest.get(g["game_id"])
            g["min_rest_days"] = None if r is None else round(float(r), 2)
    return games


def _open(lock_wait: float):
    from deepsports.store import Store, is_lock_conflict

    try:
        return Store(config.DB_PATH, read_only=True, lock_wait=lock_wait)
    except duckdb.IOException as e:
        if is_lock_conflict(e):
            return None
        raise


# ---------- commands ----------


def cmd_log(args: argparse.Namespace) -> int:
    from deepsports.analysis.ensemble_bets import load_predictions
    from deepsports.circa.storage import require_mounted

    now = datetime.now(UTC)
    game_date = args.date or (now.astimezone(config.LOCAL_TZ).date() + timedelta(days=1))
    out_dir = require_mounted(Path(args.out_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    p = _paths(out_dir)
    run = {"rule_version": et.RULE_VERSION, "ran_at": now.isoformat(timespec="seconds"),
           "game_date": game_date.isoformat()}  # fmt: skip
    early = load_early_lines(game_date)
    try:
        export = json.loads(Path(args.manualbets).read_text())
    except (OSError, ValueError):
        export = None
    db = _open(args.lock_wait)
    if db is None:
        append_jsonl(p["runs"], [run | {"status": "busy"}])
        print(f"early-totals {game_date}: warehouse busy (a writer holds the lock); nothing logged")
        return BUSY_EXIT
    try:
        games = load_games(db.con, game_date)
        preds = load_predictions(db.con, et.LEAGUE, [g["game_id"] for g in games], now)
    finally:
        db.close()
    bets, counts = et.find_bets(games, preds, export, early, now, game_date.isoformat())
    with (out_dir / ".lock").open("a") as lk:  # one logger at a time: no duplicate rows
        fcntl.flock(lk, fcntl.LOCK_EX)
        new = et.new_rows(read_jsonl(p["bets"]), bets)
        append_jsonl(p["bets"], new)
        have = {"caesars": early is not None, "manualbets": bool(counts["mb_export_ok"])}
        missing = [k for k, ok in have.items() if not ok]
        run |= {"status": "ok" if not missing else "missing " + ",".join(missing),
                "book_grabbed_at": (early or {}).get("grabbed_at"),
                "mb_created_at": (export or {}).get("created_at"),
                **counts, "new": len(new)}  # fmt: skip
        append_jsonl(p["runs"], [run])
    note = f" (missing: {', '.join(missing)})" if missing else ""
    print(
        f"early-totals {game_date}: {counts['games']} games,"
        f" {counts['all_inputs']} with DS+MB+Caesars, {len(bets)} qualify, {len(new)} new{note}"
    )
    for b in new:
        print(f"  {b['away']} @ {b['home']} {b['side']} {b['line']:g} {b['price']:+d}"
              f" (DS +{b['ds_edge']:.1f}, MB +{b['mb_edge']:.1f})")  # fmt: skip
    return 0


def cmd_grade(args: argparse.Namespace) -> int:
    from deepsports.analysis.ensemble_bets import load_finals
    from deepsports.analysis.model_picks import load_closes
    from deepsports.books import grab

    p = _paths(Path(args.out_dir))
    bets = [b for b in read_jsonl(p["bets"]) if b.get("rule_version") == et.RULE_VERSION]
    ids = sorted({str(b["game_id"]) for b in bets})
    db = _open(args.lock_wait)
    if db is None:
        print("early-totals grade: warehouse busy (a writer holds the lock); try again later")
        return BUSY_EXIT
    try:
        finals = load_finals(db.con, ids)
        closes = load_closes(db.con, ids)
    finally:
        db.close()
    dayof: dict[str, dict] = {}
    for d in sorted({b["game_date"] for b in bets}):
        dayof |= et.book_totals(grab.load(et.BOOK, date.fromisoformat(d)))
    graded = [
        et.grade_bet(
            b,
            finals.get(str(b["game_id"])),
            (closes.get(str(b["game_id"])) or {}).get("over_under"),
            dayof.get(str(b["game_id"])),
        )  # fmt: skip
        for b in bets
    ]
    summary = et.summarize(graded)
    if p["grade"].parent.exists():
        tmp = p["grade"].with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"summary": summary, "bets": graded}, indent=1, default=str))
        os.replace(tmp, p["grade"])
    print(json.dumps(summary, indent=1) if args.json else et.render(summary))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    p = _paths(Path(args.out_dir))
    bets = [b for b in read_jsonl(p["bets"]) if b.get("rule_version") == et.RULE_VERSION]
    runs = read_jsonl(p["runs"])
    days = sorted({b["game_date"] for b in bets})
    span = f", game days {days[0]} to {days[-1]}" if days else ""
    print(f"early-totals {et.RULE_VERSION}: {len(bets)} bets logged{span}"
          f" (verdict at {et.VERDICT_N} graded)")  # fmt: skip
    for r in runs[-args.runs :]:
        print(f"  {r.get('ran_at')} for {r.get('game_date')}: {r.get('status')},"
              f" {r.get('bets', 0)} qualify, {r.get('new', 0)} new")  # fmt: skip
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="deepsports early-totals",
        description="Night-before college totals forward test (et-v1, watch-only).",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    lg = sub.add_parser("log", help="log tomorrow's qualifying bets (idempotent; run at 21:00)")
    lg.add_argument("--date", type=date.fromisoformat, help="game day (default: tomorrow, local)")
    lg.add_argument("--manualbets", default=str(MB_EXPORT), help="ManualBets export JSON")
    gr = sub.add_parser("grade", help="CLV + W/L/P of every logged bet vs the pre-registered test")
    gr.add_argument("--json", action="store_true")
    st = sub.add_parser("status", help="files only: bets logged and the last runs")
    st.add_argument("--runs", type=int, default=5)
    for s in (lg, gr, st):
        s.add_argument("--out-dir", default=str(OUT_DIR))
    for s in (lg, gr):
        s.add_argument("--lock-wait", type=float, default=20.0, help="seconds to wait for a writer")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config.require_data_dir()
    except config.DataDirUnavailable as e:
        print(f"early-totals: {e}", file=sys.stderr)
        return 2
    return {"log": cmd_log, "grade": cmd_grade, "status": cmd_status}[args.cmd](args)
