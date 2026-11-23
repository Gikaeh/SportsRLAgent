"""`deepsports early-totals log|grade|status|context`: the `et-v1` night-before totals forward test.

Watch-only (never places or sizes a bet). Rule and pass/fail are pre-registered in
docs/results/2026-11-15-early-totals-preregistration.md; logic in `analysis/early_totals.py`.

Files under `<REPORTS_DIR>/early-totals/` (append-only, no stakes):
- `bets.jsonl`: one row per qualifying bet; the first row per (rule version, game) is the bet.
- `runs.jsonl`: one row per `log` run (also nights with no bet, missing inputs or a busy warehouse).
- `grade.json`: the latest `grade` output (derived; rewritten each time).
- `context.jsonl`: market context of each et-v1 / et-v1-alt bet (opener, DraftKings at bet time,
  Caesars feed, WH and Circa screenshots; `analysis/early_totals_context.py`), written by its own
  `context --log` step after the 21:00 log and the Circa read; first row per (rule version, game)
  frozen. Describe-only: et-v1's files, output and exit code never depend on it.
- `alt/`: the same three files for the `et-v1-alt` shadow (`analysis/early_totals_alt.py`), logged
  by the same `log` run after et-v1 (`--no-alt` skips it) and graded with `grade --alt`. A shadow
  failure prints to stderr and never changes et-v1's files, output or exit code.

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
from deepsports.analysis import early_totals_alt as eta
from deepsports.analysis import early_totals_context as etc
from deepsports.store import PREDICTION_RESULTS_SQL

OUT_DIR = config.REPORTS_DIR / "early-totals"
MB_EXPORT = config.ROOT / ".sync" / "manualbets-export.json"
BUSY_EXIT = 3
ALT_SUBDIR = "alt"
CONTEXT_FILE = "context.jsonl"


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
    """The game day's night-before William Hill lines: the owner's opening screenshots
    (`circa read --early --book williamhill`) first, then the Caesars feed (`books.grab.load_early`)
    for any game and side the screenshots lack (amendment 2026-11-16 in the pre-registration).
    Each line is tagged `source` screenshot | feed. The caller keeps only that day's games."""
    from deepsports.books import grab
    from deepsports.circa import load_lines
    from deepsports.moon.circa import merge

    def tagged(data: dict | None, source: str) -> dict | None:
        if data is None:
            return None
        lines = [
            dict(q) | {"source": source} for q in data.get("lines") or [] if isinstance(q, dict)
        ]
        return dict(data) | {"lines": lines}

    shots = tagged(load_lines(game_date, et.BOOK, early=True), "screenshot")
    return merge(shots, tagged(grab.load_early(et.BOOK, game_date), "feed"))


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


ALT_PREDS_SQL = """
SELECT game_id, model_version, pred_total, created_at FROM predictions
WHERE model = 'v1' AND model_version = ? AND created_at <= ? AND game_id IN ({ids})
QUALIFY row_number() OVER (PARTITION BY game_id ORDER BY created_at DESC) = 1
"""


def load_alt_predictions(
    con: duckdb.DuckDBPyConnection, game_ids: Sequence[str], now: datetime
) -> dict[str, dict[str, Any]]:
    """Latest ncaab-v1.1alt row per game made at or before `now`."""
    if not game_ids:
        return {}
    sql = ALT_PREDS_SQL.format(ids=", ".join("?" for _ in game_ids))
    rows = con.execute(sql, [eta.ALT_DS_VERSION, now, *game_ids]).fetchall()
    cols = ("game_id", "model_version", "pred_total", "created_at")
    return {r[0]: dict(zip(cols, r, strict=True)) for r in rows}


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
        if not args.no_alt:
            _shadow(_alt_busy, out_dir, run)
        return BUSY_EXIT
    alt_preds: dict | Exception = {}
    try:
        games = load_games(db.con, game_date)
        preds = load_predictions(db.con, et.LEAGUE, [g["game_id"] for g in games], now)
        if not args.no_alt:
            try:
                alt_preds = load_alt_predictions(db.con, [g["game_id"] for g in games], now)
            except Exception as e:  # the shadow never breaks et-v1
                alt_preds = e
    finally:
        db.close()
    bets, counts = et.find_bets(games, preds, export, early, now, game_date.isoformat())
    with (out_dir / ".lock").open("a") as lk:  # one logger at a time: no duplicate rows
        fcntl.flock(lk, fcntl.LOCK_EX)
        new = et.new_rows(read_jsonl(p["bets"]), bets)
        append_jsonl(p["bets"], new)
        have = {"wh lines": early is not None, "manualbets": bool(counts["mb_export_ok"])}
        missing = [k for k, ok in have.items() if not ok]
        run |= {"status": "ok" if not missing else "missing " + ",".join(missing),
                "book_grabbed_at": (early or {}).get("grabbed_at"),
                "book_read_at": (early or {}).get("read_at"),
                "line_sources": (early or {}).get("sources"),
                "mb_created_at": (export or {}).get("created_at"),
                **counts, "new": len(new)}  # fmt: skip
        append_jsonl(p["runs"], [run])
    note = f" (missing: {', '.join(missing)})" if missing else ""
    print(
        f"early-totals {game_date}: {counts['games']} games,"
        f" {counts['all_inputs']} with DS+MB+WH line, {len(bets)} qualify, {len(new)} new{note}"
    )
    for b in new:
        print(f"  {b['away']} @ {b['home']} {b['side']} {b['line']:g} {b['price']:+d}"
              f" (DS +{b['ds_edge']:.1f}, MB +{b['mb_edge']:.1f})")  # fmt: skip
    if not args.no_alt:
        inputs = (games, preds, alt_preds, export, early, now, game_date, bets, run)
        _shadow(_alt_log, out_dir, inputs)
    return 0


# ---------- et-v1-alt shadow (runs after et-v1; its failures stay out of et-v1's path) ----------


def _shadow(fn, out_dir: Path, payload) -> None:
    try:
        fn(out_dir / ALT_SUBDIR, payload)
    except Exception as e:
        print(f"early-totals {eta.ALT_RULE_VERSION}: shadow failed ({e!r}); et-v1 unaffected",
              file=sys.stderr)  # fmt: skip


def _alt_run(run: dict) -> dict:
    return {"rule_version": eta.ALT_RULE_VERSION, "ran_at": run["ran_at"],
            "game_date": run["game_date"]}  # fmt: skip


def _alt_busy(alt_dir: Path, run: dict) -> None:
    alt_dir.mkdir(parents=True, exist_ok=True)
    append_jsonl(_paths(alt_dir)["runs"], [_alt_run(run) | {"status": "busy"}])


def _alt_log(alt_dir: Path, payload) -> None:
    games, preds, alt_preds, export, early, now, game_date, v1_bets, v1_run = payload
    alt_dir.mkdir(parents=True, exist_ok=True)
    p = _paths(alt_dir)
    run = _alt_run(v1_run)
    if isinstance(alt_preds, Exception):
        append_jsonl(p["runs"], [run | {"status": f"error: {alt_preds!r}"}])
        raise alt_preds
    bets, counts = eta.find_alt_bets(
        games, preds, alt_preds, export, early, now, game_date.isoformat()
    )
    with p["lock"].open("a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        new = et.new_rows(read_jsonl(p["bets"]), bets)
        append_jsonl(p["bets"], new)
        append_jsonl(p["runs"], [run | {"status": v1_run.get("status"), **counts,
                                        "new": len(new)}])  # fmt: skip
    diff = eta.differences(v1_bets, bets)
    what = ", ".join(f"{d['game_id']} {d['kind']}" for d in diff) or "none"
    print(
        f"early-totals {eta.ALT_RULE_VERSION} {game_date}: {len(bets)} qualify, {len(new)} new"
        f" (alt DS on {counts['ds_alt']} games, v1 fallback {counts['ds_fallback_v1']});"
        f" differs from et-v1 on: {what}"
    )
    for b in new:
        print(f"  {b['away']} @ {b['home']} {b['side']} {b['line']:g} {b['price']:+d}"
              f" (DS +{b['ds_edge']:.1f}, MB +{b['mb_edge']:.1f})")  # fmt: skip


def cmd_grade(args: argparse.Namespace) -> int:
    from deepsports.analysis.ensemble_bets import load_finals
    from deepsports.analysis.model_picks import load_closes
    from deepsports.books import grab

    if args.alt:
        return cmd_grade_alt(args)
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


MODELS_SQL = f"""
SELECT r.game_id, r.start_time_utc, r.model_version, r.pred_total, r.actual_total, v.elevation_m
FROM ({PREDICTION_RESULTS_SQL}) r
JOIN games g ON g.game_id = r.game_id
LEFT JOIN venues v ON v.venue_id = g.venue_id
WHERE r.league = 'ncaab' AND r.model = 'v1' AND r.model_version IN (?, ?)
  AND g.season_year = ? AND r.pred_total IS NOT NULL
"""


def load_model_rows(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    """Graded 2026-27 college games with both a pre-tip ncaab-v1 and ncaab-v1.1alt total:
    {game_id, day (local), elevation_m, actual, v1, alt}."""
    by_game: dict[str, dict[str, Any]] = {}
    params = [eta.BASE_DS_VERSION, eta.ALT_DS_VERSION, eta.SEASON_YEAR]
    for gid, start, version, pred, actual, elev in con.execute(MODELS_SQL, params).fetchall():
        day = start.astimezone(config.LOCAL_TZ).date().isoformat()
        g = by_game.setdefault(
            gid, {"game_id": gid, "elevation_m": elev, "actual": actual, "day": day}
        )
        g["v1" if version == eta.BASE_DS_VERSION else "alt"] = float(pred)
    return [g for g in by_game.values() if "v1" in g and "alt" in g]


def _grade_rows(bets, finals, closes) -> list[dict[str, Any]]:
    return [
        et.grade_bet(
            b,
            finals.get(str(b["game_id"])),
            (closes.get(str(b["game_id"])) or {}).get("over_under"),
        )  # fmt: skip
        for b in bets
    ]


def cmd_grade_alt(args: argparse.Namespace) -> int:
    """The et-v1-alt shadow vs et-v1 on paired nights, plus ncaab-v1.1alt vs ncaab-v1 totals.
    Reads both logs; writes only `alt/grade.json`."""
    from deepsports.analysis.ensemble_bets import load_finals
    from deepsports.analysis.model_picks import load_closes

    p, pa = _paths(Path(args.out_dir)), _paths(Path(args.out_dir) / ALT_SUBDIR)
    v1 = [b for b in read_jsonl(p["bets"]) if b.get("rule_version") == et.RULE_VERSION]
    alt = [b for b in read_jsonl(pa["bets"]) if b.get("rule_version") == eta.ALT_RULE_VERSION]
    ran = [(r["game_date"], str(r.get("status", ""))) for r in read_jsonl(pa["runs"])]
    paired = {d for d, st in ran if st != "busy" and not st.startswith("error")}
    ids = sorted({str(b["game_id"]) for b in v1 + alt})
    db = _open(args.lock_wait)
    if db is None:
        print("early-totals grade: warehouse busy (a writer holds the lock); try again later")
        return BUSY_EXIT
    try:
        finals = load_finals(db.con, ids)
        closes = load_closes(db.con, ids)
        try:
            models = load_model_rows(db.con)
        except duckdb.Error:  # no venues table / older warehouse
            models = None
    finally:
        db.close()
    today = datetime.now(UTC).astimezone(config.LOCAL_TZ).date()
    summary = eta.summarize(
        _grade_rows(v1, finals, closes), _grade_rows(alt, finals, closes), paired, models, today
    )
    if pa["grade"].parent.exists():
        tmp = pa["grade"].with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"summary": summary}, indent=1, default=str))
        os.replace(tmp, pa["grade"])
    print(json.dumps(summary, indent=1, default=str) if args.json else eta.render(summary))
    return 0


# ---------- market context (describe-only; its own command, never part of `log`) ----------

SNAPS_SQL = """
SELECT game_id, source, provider, captured_at, over_under FROM odds_snapshots
WHERE source IN ('opening', 'pregame') AND over_under IS NOT NULL AND game_id IN ({ids})
"""


def load_snaps(con: duckdb.DuckDBPyConnection, game_ids: Sequence[str]) -> dict[str, list[dict]]:
    """Opening + pregame snapshot rows per game."""
    if not game_ids:
        return {}
    sql = SNAPS_SQL.format(ids=", ".join("?" for _ in game_ids))
    out: dict[str, list[dict]] = {}
    for gid, src, prov, cap, ou in con.execute(sql, list(game_ids)).fetchall():
        out.setdefault(gid, []).append(
            {"source": src, "provider": prov, "captured_at": cap, "over_under": ou}
        )
    return out


def _all_bets(out_dir: Path) -> list[dict]:
    v1 = read_jsonl(_paths(out_dir)["bets"])
    alt = read_jsonl(_paths(out_dir / ALT_SUBDIR)["bets"])
    return [b for b in v1 if b.get("rule_version") == et.RULE_VERSION] + [
        b for b in alt if b.get("rule_version") == eta.ALT_RULE_VERSION
    ]


def day_lines(game_date: date) -> tuple[dict | None, dict | None, dict | None]:
    """(WH screenshots, Caesars feed, Circa screenshots): a game day's night-before payloads."""
    from deepsports.books import grab
    from deepsports.circa import load_lines

    return (load_lines(game_date, et.BOOK, early=True), grab.load_early(et.BOOK, game_date),
            load_lines(game_date, "circa", early=True))  # fmt: skip


def cmd_context_log(args: argparse.Namespace) -> int:
    """Append a context row for each logged bet that lacks one: one game day's bets (default
    tomorrow), or with --backfill every logged bet (rows flagged backfilled)."""
    from deepsports.circa.storage import require_mounted

    now = datetime.now(UTC)
    out_dir = require_mounted(Path(args.out_dir))
    path = out_dir / CONTEXT_FILE
    bets = _all_bets(out_dir)
    label = "backfill"
    if not args.backfill:
        day = args.date or (now.astimezone(config.LOCAL_TZ).date() + timedelta(days=1))
        label = day.isoformat()
        bets = [b for b in bets if b.get("game_date") == label]
    todo = etc.missing(bets, read_jsonl(path))
    if not todo:
        print(f"early-totals context {label}: 0 bets need a row")
        return 0
    db = _open(args.lock_wait)
    if db is None:
        print(f"early-totals context {label}: warehouse busy (a writer holds the lock);"
              " nothing written")  # fmt: skip
        return BUSY_EXIT
    try:
        snaps = load_snaps(db.con, sorted({str(b["game_id"]) for b in todo}))
    finally:
        db.close()
    lines = {d: day_lines(date.fromisoformat(d)) for d in sorted({b["game_date"] for b in todo})}
    rows, errors = [], 0
    for b in todo:
        try:
            rows.append(etc.context_row(b, snaps.get(str(b["game_id"]), []),
                                        *lines[b["game_date"]], now, args.backfill))  # fmt: skip
        except Exception as e:  # one bad bet never blocks the others
            errors += 1
            print(f"early-totals context: {b.get('rule_version')} {b.get('game_id')}: {e!r}",
                  file=sys.stderr)  # fmt: skip
    with (out_dir / ".lock").open("a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        new = etc.missing(rows, read_jsonl(path))
        append_jsonl(path, new)
    dk = sum(r["dk_total"] is not None for r in new)
    ci = sum(r["circa_total"] is not None for r in new)
    err = f", {errors} errors" if errors else ""
    print(f"early-totals context {label}: {len(new)} rows written"
          f" (DK at bet time {dk}, Circa {ci}{err})")  # fmt: skip
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    """Describe-only view: win % / CLV split by momentum and by Circa vs WH. Prints only."""
    from deepsports.analysis.ensemble_bets import load_finals
    from deepsports.analysis.model_picks import load_closes

    if args.log or args.backfill:
        return cmd_context_log(args)
    out_dir = Path(args.out_dir)
    rule = eta.ALT_RULE_VERSION if args.alt else et.RULE_VERSION
    bets = [b for b in _all_bets(out_dir) if b["rule_version"] == rule]
    rows = read_jsonl(out_dir / CONTEXT_FILE)
    ids = sorted({str(b["game_id"]) for b in bets})
    db = _open(args.lock_wait)
    if db is None:
        print("early-totals context: warehouse busy (a writer holds the lock); try again later")
        return BUSY_EXIT
    try:
        finals = load_finals(db.con, ids)
        closes = load_closes(db.con, ids)
        snaps = load_snaps(db.con, ids)
    finally:
        db.close()
    openers = {}
    for g in ids:
        op = etc.market_at(snaps.get(g, []), None)["opener_total"]
        if op is not None:
            openers[g] = op
    s = etc.summarize(_grade_rows(bets, finals, closes), rows, openers, rule)
    print(json.dumps(s, indent=1, default=str) if args.json else etc.render(s))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    if args.alt:
        p = _paths(Path(args.out_dir) / ALT_SUBDIR)
        bets = [b for b in read_jsonl(p["bets"]) if b.get("rule_version") == eta.ALT_RULE_VERSION]
        days = sorted({b["game_date"] for b in bets})
        span = f", game days {days[0]} to {days[-1]}" if days else ""
        print(f"early-totals {eta.ALT_RULE_VERSION} (shadow): {len(bets)} bets logged{span}"
              f" (verdict after {eta.VERDICT_AFTER.isoformat()})")  # fmt: skip
        for r in read_jsonl(p["runs"])[-args.runs :]:
            print(f"  {r.get('ran_at')} for {r.get('game_date')}: {r.get('status')},"
                  f" {r.get('bets', 0)} qualify, {r.get('new', 0)} new")  # fmt: skip
        return 0
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
    lg.add_argument("--no-alt", action="store_true", help="skip the et-v1-alt shadow log")
    gr = sub.add_parser("grade", help="CLV + W/L/P of every logged bet vs the pre-registered test")
    gr.add_argument("--json", action="store_true")
    st = sub.add_parser("status", help="files only: bets logged and the last runs")
    st.add_argument("--runs", type=int, default=5)
    cx = sub.add_parser(
        "context",
        help="bets' market context: --log/--backfill write rows, else a describe-only split",
    )
    cx.add_argument("--log", action="store_true", help="write rows for one game day's bets")
    cx.add_argument(
        "--backfill", action="store_true", help="rows for every logged bet lacking one (backfilled)"
    )
    cx.add_argument(
        "--date", type=date.fromisoformat, help="game day for --log (default: tomorrow)"
    )
    cx.add_argument("--json", action="store_true")
    for s in (gr, st, cx):
        s.add_argument("--alt", action="store_true", help="the et-v1-alt shadow (paired vs et-v1)")
    for s in (lg, gr, st, cx):
        s.add_argument("--out-dir", default=str(OUT_DIR))
    for s in (lg, gr, cx):
        s.add_argument("--lock-wait", type=float, default=20.0, help="seconds to wait for a writer")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config.require_data_dir()
    except config.DataDirUnavailable as e:
        print(f"early-totals: {e}", file=sys.stderr)
        return 2
    return {"log": cmd_log, "grade": cmd_grade, "status": cmd_status, "context": cmd_context}[
        args.cmd
    ](args)
