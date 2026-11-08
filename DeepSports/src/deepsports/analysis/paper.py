"""Forward paper-trade log (watch-only, no money): three frozen rules from the DeepSeek edge
study's "Top 3 candidates" (collab/deepseek/EDGE_REPORT.md), logged before tip-off during the
2026-27 season and graded afterwards. None of them is an edge claim; the point is an honest
out-of-sample record. Definitions are frozen in RULES and in docs/DECISIONS.md (2026-11-04);
changing one means a new rule_version, never an edit.

- `select_bets(con, now, days)`: read-only; the bets the rules would log now, plus skip counts.
- `log_bets(store, now, days)`: writes them to `paper_bets` (insert-only: the first logged bet
  for a (rule, game, market) is frozen).
- `paper_report(con)`: per rule record, win%, ROI with a day-clustered bootstrap CI, units,
  drawdown and CLV vs the closing line, graded with `analysis.betting`.

What every rule shares: regular-season games (season_type 2) whose US/Eastern game day is
within the next `days` days (default 1: today), that have not started (state 'pre' and tip
after `now`), priced off the latest `pregame` odds snapshot captured at or before `now`
(sanity-limited total), flat 1 unit at -110.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import duckdb

from deepsports.analysis import betting
from deepsports.analysis.fatigue import top8_load
from deepsports.analysis.model import MODEL_NAME
from deepsports.store import SANE_LIMITS

EASTERN = ZoneInfo("America/New_York")
PRICE = -110
STAKE = 1.0
SEASON_TYPES = (2,)
LINE_SOURCE = "pregame"


@dataclass(frozen=True)
class PaperRule:
    name: str
    version: str
    league: str
    market: str
    signal: str  # model_total | load_under
    threshold: float
    model_version: str | None  # predictions.model_version used (model = "v1"); exact match
    description: str
    window_hours: float = 72.0  # load_under only
    exclude_hours: float = 27.0  # load_under only


RULES: tuple[PaperRule, ...] = (
    PaperRule(
        name="ncaab-total-t7",
        version="1",
        league="ncaab",
        market="total",
        signal="model_total",
        threshold=7.0,
        model_version="ncaab-v1",  # the gated version (both teams >= 5 games); never -early
        description="college v1 pred_total vs the market total; bet the model's side "
        "(over if pred_total - line >= 7, under if <= -7)",
    ),
    PaperRule(
        name="nba-total-t4",
        version="1",
        league="nba",
        market="total",
        signal="model_total",
        threshold=4.0,
        model_version="v1.1",
        description="NBA v1.1 pred_total vs the market total; bet the model's side "
        "(over if pred_total - line >= 4, under if <= -4)",
    ),
    PaperRule(
        name="nba-load-under",
        version="1",
        league="nba",
        market="total",
        signal="load_under",
        threshold=470.0,
        model_version=None,
        description="under when both teams' top-8 minutes in games tipping 27-72 h before "
        "tip-off sum to >= 470 (edge study B3 min3n; threshold = dev mean + 1 SD, rounded)",
    ),
)
RULES_BY_NAME = {r.name: r for r in RULES}


def _rows(con: duckdb.DuckDBPyConnection, sql: str, params: Sequence[Any] = ()) -> list[dict]:
    cur = con.execute(sql, list(params))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def _marks(xs: Sequence[Any]) -> str:
    return ", ".join("?" for _ in xs)


def upcoming_targets(
    con: duckdb.DuckDBPyConnection, league: str, now: datetime, days: int = 1
) -> list[dict[str, Any]]:
    """Not-started regular-season games of `league` whose US/Eastern game day is today .. today
    + days - 1 (as of `now`), with both teams known in that league."""
    today = now.astimezone(EASTERN).date()
    last = today + timedelta(days=max(days, 1) - 1)
    return _rows(
        con,
        f"""SELECT g.game_id, g.league, g.season_year, g.season_type, g.start_time_utc,
                   g.home_team_id, g.away_team_id
            FROM games g
            JOIN teams h ON h.league = g.league AND h.team_id = g.home_team_id
            JOIN teams a ON a.league = g.league AND a.team_id = g.away_team_id
            WHERE g.league = ? AND g.state = 'pre' AND g.start_time_utc > ?
              AND g.season_type IN ({_marks(SEASON_TYPES)})
              AND CAST(timezone('America/New_York', g.start_time_utc) AS DATE)
                  BETWEEN ? AND ?
            ORDER BY g.start_time_utc, g.game_id""",
        [league, now, *SEASON_TYPES, today, last],
    )


def pregame_lines(
    con: duckdb.DuckDBPyConnection, game_ids: Sequence[str], now: datetime
) -> dict[str, dict[str, Any]]:
    """Latest `pregame` odds snapshot per game captured at or before `now`."""
    if not game_ids:
        return {}
    rows = _rows(
        con,
        f"""SELECT game_id, captured_at, provider, details, spread_home, over_under
            FROM odds_snapshots
            WHERE source = ? AND captured_at <= ? AND game_id IN ({_marks(game_ids)})
            QUALIFY row_number() OVER (PARTITION BY game_id ORDER BY captured_at DESC) = 1""",
        [LINE_SOURCE, now, *game_ids],
    )
    return {r["game_id"]: r for r in rows}


def _sane_total(league: str, total: float | None) -> float | None:
    lim = SANE_LIMITS.get(league)
    if total is None or lim is None:
        return None
    return float(total) if lim[1] <= total <= lim[2] else None


def _predictions(
    con: duckdb.DuckDBPyConnection, rule: PaperRule, game_ids: Sequence[str], now: datetime
) -> dict[str, dict[str, Any]]:
    if not game_ids:
        return {}
    rows = _rows(
        con,
        f"""SELECT game_id, model_version, created_at, pred_total FROM predictions
            WHERE model = ? AND model_version = ? AND created_at <= ?
              AND game_id IN ({_marks(game_ids)})""",
        [MODEL_NAME, rule.model_version, now, *game_ids],
    )
    return {r["game_id"]: r for r in rows}


def _iso(t: datetime | None) -> str | None:
    return t.astimezone(UTC).isoformat() if t is not None else None


def _bet(rule, g, line_row, line, side, model_value, now, inputs) -> dict[str, Any]:
    return {
        "rule": rule.name,
        "rule_version": rule.version,
        "game_id": g["game_id"],
        "league": rule.league,
        "market": rule.market,
        "side": side,
        "line": line,
        "price": PRICE,
        "stake": STAKE,
        "model_value": model_value,
        "line_source": LINE_SOURCE,
        "line_provider": line_row.get("provider"),
        "line_captured_at": line_row["captured_at"],
        "logged_at": now,
        "start_time_utc": g["start_time_utc"],
        "inputs_json": {**inputs, "line_details": line_row.get("details")},
    }


def model_total_bets(
    con: duckdb.DuckDBPyConnection,
    rule: PaperRule,
    targets: list[dict[str, Any]],
    lines: dict[str, dict[str, Any]],
    now: datetime,
    skips: Counter,
) -> list[dict[str, Any]]:
    """Bet the model's side of the total when |pred_total - line| >= threshold."""
    preds = _predictions(con, rule, [g["game_id"] for g in targets], now)
    out = []
    for g in targets:
        lr = lines.get(g["game_id"])
        line = _sane_total(rule.league, lr["over_under"]) if lr else None
        p = preds.get(g["game_id"])
        if line is None:
            skips["no_line"] += 1
            continue
        if p is None or p["pred_total"] is None:
            skips["no_prediction"] += 1
            continue
        edge = float(p["pred_total"]) - line
        if abs(edge) < rule.threshold:
            skips["below_threshold"] += 1
            continue
        inputs = {
            "model": MODEL_NAME,
            "model_version": p["model_version"],
            "prediction_created_at": _iso(p["created_at"]),
            "edge": round(edge, 4),
        }
        side = "over" if edge > 0 else "under"
        out.append(_bet(rule, g, lr, line, side, float(p["pred_total"]), now, inputs))
    return out


def team_loads(
    con: duckdb.DuckDBPyConnection,
    targets: list[dict[str, Any]],
    window_hours: float = 72.0,
    exclude_hours: float = 27.0,
) -> tuple[dict[str, dict[str, float | None]], set[str]]:
    """(top8_load for each target, target ids whose recent history is incomplete). History is
    every regular-season game of the target's league and season with both teams known;
    a target is incomplete when one of its teams has a finished game in the window
    [tip - window_hours, tip) without player box scores (data not collected yet)."""
    if not targets:
        return {}, set()
    league = targets[0]["league"]
    seasons = sorted({int(g["season_year"]) for g in targets})
    ids = [g["game_id"] for g in targets]
    games = _rows(
        con,
        f"""SELECT g.game_id, g.league, g.season_year, g.start_time_utc, g.home_team_id,
                   g.away_team_id, g.completed AND g.status = 'STATUS_FINAL' AS final,
                   EXISTS (SELECT 1 FROM player_game_stats p WHERE p.game_id = g.game_id)
                       AS has_box
            FROM games g
            JOIN teams h ON h.league = g.league AND h.team_id = g.home_team_id
            JOIN teams a ON a.league = g.league AND a.team_id = g.away_team_id
            WHERE g.league = ? AND g.season_year IN ({_marks(seasons)})
              AND g.season_type IN ({_marks(SEASON_TYPES)})
              AND (g.completed AND g.status = 'STATUS_FINAL' OR g.game_id IN ({_marks(ids)}))""",
        [league, *seasons, *SEASON_TYPES, *ids],
    )
    stats = _rows(
        con,
        f"""SELECT p.game_id, p.team_id, p.athlete_id, p.minutes
            FROM player_game_stats p
            JOIN games g USING (game_id)
            JOIN teams t ON t.league = p.league AND t.team_id = p.team_id AND t.listed
            WHERE p.league = ? AND g.season_year IN ({_marks(seasons)})
              AND g.season_type IN ({_marks(SEASON_TYPES)})""",
        [league, *seasons, *SEASON_TYPES],
    )
    for g in games:
        g["start_epoch"] = g["start_time_utc"].timestamp()
    loads = top8_load(games, stats, window_hours, exclude_hours)
    incomplete = set()
    by_team: dict[str, list[dict[str, Any]]] = {}
    for g in games:
        if g["final"]:
            for t in (g["home_team_id"], g["away_team_id"]):
                by_team.setdefault(t, []).append(g)
    for tg in targets:
        lo = tg["start_time_utc"] - timedelta(hours=window_hours)
        for t in (tg["home_team_id"], tg["away_team_id"]):
            if any(
                lo <= g["start_time_utc"] < tg["start_time_utc"] and not g["has_box"]
                for g in by_team.get(t, [])
            ):
                incomplete.add(tg["game_id"])
    return {i: loads[i] for i in ids if i in loads}, incomplete


def load_under_bets(
    con: duckdb.DuckDBPyConnection,
    rule: PaperRule,
    targets: list[dict[str, Any]],
    lines: dict[str, dict[str, Any]],
    now: datetime,
    skips: Counter,
) -> list[dict[str, Any]]:
    """Under when home + away top-8 load (27-72 h window) >= threshold."""
    loads, incomplete = team_loads(con, targets, rule.window_hours, rule.exclude_hours)
    out = []
    for g in targets:
        lr = lines.get(g["game_id"])
        line = _sane_total(rule.league, lr["over_under"]) if lr else None
        if line is None:
            skips["no_line"] += 1
            continue
        if g["game_id"] in incomplete:
            skips["incomplete_history"] += 1
            continue
        ld = loads.get(g["game_id"]) or {}
        if ld.get("home") is None or ld.get("away") is None:
            skips["no_load"] += 1  # e.g. a team's season opener: no top-8 yet
            continue
        total_load = ld["home"] + ld["away"]
        if total_load < rule.threshold:
            skips["below_threshold"] += 1
            continue
        inputs = {
            "home_load": ld["home"],
            "away_load": ld["away"],
            "window_hours": rule.window_hours,
            "exclude_hours": rule.exclude_hours,
        }
        out.append(_bet(rule, g, lr, line, "under", total_load, now, inputs))
    return out


SIGNALS = {"model_total": model_total_bets, "load_under": load_under_bets}


def select_bets(
    con: duckdb.DuckDBPyConnection,
    now: datetime | None = None,
    days: int = 1,
    rules: Sequence[PaperRule] = RULES,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, int]]]:
    """(bet rows for Store.add_paper_bets, {rule: skip counts}) as of `now`. Read-only."""
    now = now or datetime.now(UTC)
    bets: list[dict[str, Any]] = []
    skipped: dict[str, dict[str, int]] = {}
    targets_by_league: dict[str, list[dict[str, Any]]] = {}
    for rule in rules:
        if rule.league not in targets_by_league:
            targets_by_league[rule.league] = upcoming_targets(con, rule.league, now, days)
        targets = targets_by_league[rule.league]
        lines = pregame_lines(con, [g["game_id"] for g in targets], now)
        skips: Counter = Counter()
        bets += SIGNALS[rule.signal](con, rule, targets, lines, now, skips)
        skipped[rule.name] = dict(skips)
    return bets, skipped


def log_bets(store, now: datetime | None = None, days: int = 1) -> dict[str, Any]:
    """Select and insert today's qualifying bets. Returns {rule: {qualifying, new, skipped}}."""
    now = now or datetime.now(UTC)
    bets, skipped = select_bets(store.con, now, days)
    out = {}
    for rule in RULES:
        mine = [b for b in bets if b["rule"] == rule.name]
        out[rule.name] = {
            "qualifying": len(mine),
            "new": store.add_paper_bets(mine),
            "skipped": skipped.get(rule.name, {}),
        }
    return out


# ---------- report ----------


def _has(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    q = "SELECT count(*) FROM information_schema.tables WHERE table_name = ?"
    return con.execute(q, [name]).fetchone()[0] > 0


def graded_rows(con: duckdb.DuckDBPyConnection, rule: str | None = None) -> list[dict[str, Any]]:
    """Rows of the paper_results view (finished games), optionally for one rule."""
    if not _has(con, "paper_results"):
        return []
    where, params = ("WHERE rule = ?", [rule]) if rule else ("", [])
    return _rows(
        con, f"SELECT * FROM paper_results {where} ORDER BY start_time_utc, game_id", params
    )


def grade_rule(rows: list[dict[str, Any]], seed: int = 42) -> betting.GradeResult:
    """Grade one rule's paper_results rows with the betting library. Bets count as taken
    before the close (timing 'open'), so CLV compares the logged line with the closing one."""
    bets, games, lines = [], {}, {}
    for r in rows:
        bets.append(
            {
                "game_id": r["game_id"],
                "league": r["league"],
                "market": r["market"],
                "side": r["side"],
                "line": r["line"],
                "price": r["price"],
                "stake": r["stake"],
                "timing": "open",
                "variant": f"{r['rule']}@{r['rule_version']}",
            }
        )
        games[r["game_id"]] = {
            "game_id": r["game_id"],
            "home_score": r["home_score"],
            "away_score": r["away_score"],
            "tip_date": str(r["tip_date"]),
        }
        lines[r["game_id"]] = {
            "game_id": r["game_id"],
            "open_spread_home": r["line"] if r["market"] == "spread" else None,
            "close_spread_home": r["close_spread_home"],
            "open_total": r["line"] if r["market"] == "total" else None,
            "close_total": r["close_total"],
        }
    return betting.grade(bets, list(games.values()), list(lines.values()), seed=seed)


def paper_report(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    """Per rule: logged / graded / pending counts and the graded summary (record, win%, ROI
    with a 95% day-clustered bootstrap CI, units, max drawdown, CLV). Read-only."""
    has_log = _has(con, "paper_bets")
    out = []
    for rule in RULES:
        logged = (
            con.execute("SELECT count(*) FROM paper_bets WHERE rule = ?", [rule.name]).fetchone()[0]
            if has_log
            else 0
        )
        rows = graded_rows(con, rule.name)
        entry: dict[str, Any] = {
            "rule": rule.name,
            "rule_version": rule.version,
            "league": rule.league,
            "definition": asdict(rule),
            "logged": logged,
            "graded": len(rows),
            "pending": logged - len(rows),
            "summary": None,
        }
        if rows:
            s = grade_rule(rows).summary
            entry["summary"] = {
                k: s[k]
                for k in (
                    "record",
                    "win_pct",
                    "roi",
                    "ci_low",
                    "ci_high",
                    "units",
                    "max_drawdown_units",
                    "clv_n",
                    "clv_mean",
                    "clv_pct_positive",
                )
            }
        out.append(entry)
    return out


def _pct(x: float | None, signed: bool = False) -> str:
    if x is None:
        return "-"
    return f"{x * 100:+.1f}%" if signed else f"{x * 100:.1f}%"


def render_report(report: list[dict[str, Any]]) -> str:
    """Plain-text table for `deepsports paper report`."""
    lines = [
        "Paper trades (watch-only; flat 1u at -110, break-even 52.4%)",
        f"{'rule':16s} {'logged':>6s} {'graded':>6s} {'W-L-P':>9s} {'win%':>6s} "
        f"{'ROI':>7s} {'95% CI':>17s} {'units':>7s} {'CLV':>6s}",
    ]
    for e in report:
        s = e["summary"] or {}
        ci = (
            f"{_pct(s.get('ci_low'), True)}..{_pct(s.get('ci_high'), True)}"
            if s.get("ci_low") is not None
            else "-"
        )
        clv = f"{s['clv_mean']:+.2f}" if s.get("clv_mean") is not None else "-"
        units = f"{s['units']:+.2f}" if s else "-"
        lines.append(
            f"{e['rule']:16s} {e['logged']:6d} {e['graded']:6d} {s.get('record', '-'):>9s} "
            f"{_pct(s.get('win_pct')):>6s} {_pct(s.get('roi'), True):>7s} {ci:>17s} "
            f"{units:>7s} {clv:>6s}"
        )
    return "\n".join(lines)


def report_json(report: list[dict[str, Any]]) -> str:
    return json.dumps(report, indent=2, default=str)
