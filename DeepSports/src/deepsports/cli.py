"""deepsports CLI. Run `uv run deepsports --help`."""

import argparse
import json
import logging
import sys
import tomllib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb

from deepsports import config, pipeline
from deepsports.http import PoliteClient
from deepsports.sources.espn import LEAGUES, EspnBasketball
from deepsports.store import Store, is_lock_conflict

CALENDAR_CONFIG = config.ROOT / "config" / "calendar.toml"


def load_calendar_config() -> dict:
    if CALENDAR_CONFIG.exists():
        with open(CALENDAR_CONFIG, "rb") as f:
            return tomllib.load(f)
    return {}


def followed_teams(cfg: dict, league: str = "nba") -> list[str]:
    """Follow list for one league from config/calendar.toml: `[ncaab] teams = [...]`. For the
    NBA, `[nba] teams` or (backward compatible) the top-level `teams`."""
    section = cfg.get(league)
    teams = section.get("teams") if isinstance(section, dict) else None
    if teams is None and league == "nba":
        teams = cfg.get("teams")
    return [t.strip().upper() for t in teams or [] if t.strip()]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="deepsports", description=__doc__)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    def league_arg(parser: argparse.ArgumentParser, extra: tuple[str, ...] = ()) -> None:
        parser.add_argument(
            "--league",
            choices=[*LEAGUES, *extra],
            default="nba",
            help="nba (default) or ncaab (NCAA men's D1)",
        )

    t = sub.add_parser("teams", help="refresh the league's team list")
    league_arg(t)

    s = sub.add_parser("schedule", help="collect games for a date range (US/Eastern game days)")
    league_arg(s)
    s.add_argument("--start", type=date.fromisoformat, required=True)
    s.add_argument("--end", type=date.fromisoformat, required=True)
    s.add_argument("--refresh", action="store_true", help="ignore cached raw responses")

    b = sub.add_parser("boxscores", help="fetch box scores for final games that lack them")
    b.add_argument("--limit", type=int)
    league_arg(b)

    u = sub.add_parser(
        "update", help="routine refresh: recent results, upcoming games, odds, injuries"
    )
    u.add_argument("--back", type=int, default=3)
    u.add_argument("--ahead", type=int, default=14)
    u.add_argument("--no-injuries", action="store_true", help="skip pre-tip injury snapshots")
    league_arg(u)

    bf = sub.add_parser("backfill", help="collect a full season, e.g. 2025-26")
    bf.add_argument("--season", required=True)
    league_arg(bf)

    oh = sub.add_parser("odds-history", help="historical lines (core API) for final games")
    oh.add_argument("--with-opening", action="store_true", help="also fetch opening lines")
    oh.add_argument("--limit", type=int)
    league_arg(oh)

    osn = sub.add_parser(
        "odds-snapshot",
        help="light pregame line capture: today's + tomorrow's scoreboards, odds rows only",
    )
    league_arg(osn, ("all",))
    osn.set_defaults(league="all")
    osn.add_argument(
        "--days", type=int, default=2, help="US/Eastern game days from today (default 2)"
    )

    pt = sub.add_parser(
        "pretip",
        help="light pre-tip job: fresh NBA injury reports + model v1.1i for games tipping soon",
    )
    pt.add_argument(
        "--window-min", type=int, default=100, help="games tipping within N minutes (default 100)"
    )
    pt.add_argument(
        "--min-lead", type=int, default=5, help="skip games tipping within N minutes (default 5)"
    )

    ib = sub.add_parser(
        "injuries-backfill", help="offline: re-parse injury snapshots from cached raw summaries"
    )
    league_arg(ib)

    pb = sub.add_parser(
        "prices-backfill",
        help="offline: fill NULL spread/total prices on opening/closing odds rows from raw cache",
    )
    league_arg(pb, ("all",))
    pb.set_defaults(league="all")
    pb.add_argument("--dry-run", action="store_true", help="count matches, write nothing")

    pr = sub.add_parser(
        "predict", help="model v1: pre-tip predictions for upcoming games (writes predictions)"
    )
    league_arg(pr)
    pr.add_argument(
        "--model-version",
        help="nba: v1.0 (default), v1.1 or v1.1i (injury-aware); "
        "ncaab: ncaab-v1 (default, >=5 games per team), "
        "ncaab-v1p (prior model, >=5 games) or ncaab-v1-early (prior model, >=1 game); "
        "comma-separated for several, ncaab: all",
    )
    pr.add_argument("--days", type=int, default=14, help="predict games in the next N days")

    pa = sub.add_parser("paper", help="forward paper-trade log of frozen rules (watch-only)")
    psub = pa.add_subparsers(dest="paper_command", required=True)
    pl = psub.add_parser("log", help="log today's qualifying bets before tip-off (insert-only)")
    pl.add_argument(
        "--days", type=int, default=1, help="US/Eastern game days to cover, from today (default 1)"
    )
    prp = psub.add_parser("report", help="record, win%%, ROI and CLV per rule")
    prp.add_argument("--json", action="store_true")

    eb = sub.add_parser(
        "ensemble-bets", help="independent-agent betting vote (watch-only; /ensemble-betting)"
    )
    ebsub = eb.add_subparsers(dest="ensemble_command", required=True)
    ec = ebsub.add_parser(
        "context", help="write a run dir: slate.json + one context file per agent"
    )
    ec.add_argument("--days", type=int, default=3, help="games tipping in the next N days")
    ec.add_argument("--agents", type=int, default=5)
    ec.add_argument("--league", choices=["nba", "ncaab", "all"], default="all")
    ec.add_argument("--seed", type=int, default=0, help="shuffle seed for game order")
    ec.add_argument(
        "--context", choices=["v1", "v2"], default="v1", help="context version (ctx-v1 / ctx-v2)"
    )
    ec.add_argument(
        "--manualbets",
        metavar="JSON",
        help="ManualBets export (ManualBets/tools/export_predictions.py) to add to every game;"
        " 'none' records that it is unavailable",
    )
    ec.add_argument(
        "--tag",
        default="",
        help="appended to context_version (e.g. +tools1) so grade keeps such runs apart",
    )
    et = ebsub.add_parser("tally", help="validate picks-<agent>.json files and count votes")
    et.add_argument("run", help="run directory (from `context`)")
    etb = ebsub.add_parser("table", help="a tallied run's majority picks as a table (Discord)")
    etb.add_argument("run", help="run directory (tallied)")
    ebsub.add_parser("grade", help="grade the majority and agent picks of every finished run")

    mp = sub.add_parser(
        "model-picks", help="models-only daily picks: DeepSports + ManualBets vs lines (watch-only)"
    )
    mpsub = mp.add_subparsers(dest="picks_command", required=True)
    mpr = mpsub.add_parser("run", help="write a run dir (slate, picks, message); print the message")
    mpr.add_argument("--days", type=int, default=1, help="games tipping in the next N days")
    mpr.add_argument("--league", choices=["nba", "ncaab", "all"], default="all")
    mpr.add_argument(
        "--manualbets",
        metavar="JSON",
        required=True,
        help="ManualBets export (tools/manualbets-export.py); 'none' if it failed",
    )
    mpg = mpsub.add_parser("grade", help="record of every run: top, strong, lean, with CLV")
    mpg.add_argument(
        "--slates",
        nargs="+",
        metavar="SLATE_JSON",
        help="instead of the saved runs, apply the rule to these slate.json files (read-only;"
        " slates without ManualBets numbers are skipped)",
    )

    sub.add_parser(
        "moon",
        help="To The Moon (betting): risk ladder, proposals and a ledger of real bets (watch-only;"
        " `deepsports moon -h`)",
        add_help=False,
    )

    sub.add_parser(
        "circa",
        help="Circa screenshots: read|ingest|status (no writer lock; `deepsports circa -h`)",
        add_help=False,
    )

    sub.add_parser("migrate", help="bring the warehouse schema up to date (idempotent)")

    up = sub.add_parser("upcoming", help="list upcoming games (input for calendar sync)")
    league_arg(up, ("all",))
    up.add_argument("--days", type=int)
    up.add_argument("--teams", help="comma-separated abbreviations, e.g. GS,LAL")
    up.add_argument("--all", action="store_true", help="ignore the follow list in config")
    up.add_argument("--json", action="store_true")

    sub.add_parser("status", help="row counts and recent ingest runs")
    sub.add_parser("check", help="data-quality checks (exit 1 on hard failures)")

    sv = sub.add_parser("serve", help="run the read API + web app (docs/API.md)")
    sv.add_argument("--host", default="0.0.0.0", help="0.0.0.0 = reachable from your phone on LAN")
    sv.add_argument("--port", type=int, default=8787)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["moon"]:  # its own parser (deepsports/moon/cli.py); opens the DB itself
        from deepsports.moon.cli import main as moon_main

        return moon_main(argv[1:])
    if argv[:1] == ["circa"]:  # its own parser; files only, plus one brief read-only open
        from deepsports.circa.cli import main as circa_main

        return circa_main(argv[1:])
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    try:
        config.require_data_dir()
    except config.DataDirUnavailable as e:
        if args.command != "serve":
            print(f"error: {e}", file=sys.stderr)
            return 2
        # live scores don't need the drive; warehouse endpoints answer 503 until it's back
        print(f"warning: {e}", file=sys.stderr)
    if args.command == "serve":  # must not hold the DuckDB write lock
        import uvicorn

        from deepsports.api.app import create_app

        # proxy_headers=False: cloudflared connects from 127.0.0.1 and sends X-Forwarded-For;
        # uvicorn would otherwise swap in the public IP and the Circa upload would lose its
        # loopback check (api/circa.py).
        uvicorn.run(
            create_app(), host=args.host, port=args.port, log_level="info", proxy_headers=False
        )
        return 0
    if args.command == "odds-snapshot":  # opens the warehouse itself, only to write
        return _odds_snapshot(args)
    if args.command == "pretip":  # reads briefly, fetches unlocked, then writes briefly
        return _pretip(args)
    if args.command == "prices-backfill":  # reads, parses unlocked, then writes briefly
        return _prices_backfill(args)
    if args.command == "ensemble-bets" and args.ensemble_command == "tally":  # files only
        from pathlib import Path

        from deepsports.analysis.ensemble_bets import tally_run

        print(tally_run(Path(args.run))[0], end="")
        return 0
    if args.command == "ensemble-bets" and args.ensemble_command == "table":  # files only
        from pathlib import Path

        from deepsports.analysis.ensemble_bets import table_run

        print(table_run(Path(args.run)))
        return 0
    read_only = args.command in ("upcoming", "status", "check", "ensemble-bets", "model-picks") or (
        args.command == "paper" and args.paper_command == "report"
    )
    db = Store(read_only=read_only)
    try:
        if read_only:
            return _read_commands(args, db)
        return _collect_commands(args, db)
    finally:
        db.close()


def _collect_commands(args: argparse.Namespace, db: Store) -> int:
    if args.command == "migrate":
        if db.migration_report:
            for table, (before, after) in db.migration_report.items():
                print(f"migrated {table:20s} rows {before} -> {after}")
        else:
            print("schema up to date; nothing to migrate")
        return 0
    if args.command == "predict":
        return _predict(args, db)
    if args.command == "paper":
        return _paper_log(args, db)
    client = PoliteClient()
    src = EspnBasketball(client, args.league)
    started = datetime.now(UTC)
    stats = pipeline.RunStats()
    if args.command == "teams":
        print(f"teams: {pipeline.collect_teams(src, db)}")
    elif args.command == "schedule":
        stats = pipeline.collect_schedule(src, db, args.start, args.end, refresh=args.refresh)
    elif args.command == "boxscores":
        stats = pipeline.collect_boxscores(src, db, args.limit)
    elif args.command == "update":
        # NBA: snapshot every game's injury report. College: followed teams only (keeps the
        # request count small; ESPN currently lists no college injuries anyway).
        follow = followed_teams(load_calendar_config(), src.league)
        injury_teams = None if src.league == "nba" else follow
        stats = pipeline.update(
            src,
            db,
            args.back,
            args.ahead,
            injuries=not args.no_injuries and (src.league == "nba" or bool(follow)),
            injury_teams=injury_teams,
        )
    elif args.command == "backfill":
        stats = pipeline.backfill_season(src, db, args.season)
    elif args.command == "odds-history":
        stats = pipeline.collect_core_odds(src, db, args.with_opening, args.limit)
    elif args.command == "injuries-backfill":
        stats = pipeline.backfill_injuries_from_raw(db, client.raw_dir, src.league)
    db.log_run(
        {
            "started_at": started,
            "finished_at": datetime.now(UTC),
            "command": " ".join(sys.argv[1:]) or args.command,
            "network_requests": client.network_requests,
            "games_upserted": stats.games,
            "boxscores_upserted": stats.boxscores,
            "errors": len(stats.errors),
            "notes": "; ".join(stats.errors[:20]) or None,
        }
    )
    print(
        f"{args.command}: league={src.league} games={stats.games} boxscores={stats.boxscores} "
        f"odds={stats.odds} injuries={stats.injuries} requests={client.network_requests} "
        f"errors={len(stats.errors)}"
    )
    for err in stats.errors[:10]:
        print(f"  error: {err}", file=sys.stderr)
    return 1 if stats.errors else 0


def _warehouse_busy(lock_wait: float = 0.0) -> bool:
    """True if another process holds the DuckDB writer lock (a read-only open fails then).
    Any other open error (e.g. macOS "Operation not permitted") is raised, not called busy."""
    if not config.DB_PATH.exists():
        return False
    try:
        Store(config.DB_PATH, read_only=True, lock_wait=lock_wait).close()
    except duckdb.IOException as e:
        if is_lock_conflict(e):
            return True
        raise
    return False


def _odds_snapshot(args: argparse.Namespace) -> int:
    """Light, frequent pregame line capture (launchd, every 30 min): fetch fresh scoreboards
    for today + tomorrow, then write only `pregame` odds rows (a new row only when a line or
    price moved). It yields to every other job: if the warehouse writer lock is held before
    fetching or when writing, it prints one line and exits 0 without writing."""
    skip = "odds-snapshot: skipped, warehouse busy (another deepsports writer holds the lock)"
    try:
        busy = _warehouse_busy()
    except duckdb.IOException as e:
        print(f"odds-snapshot: FAILED, cannot open the warehouse: {e}")
        return 1
    if busy:
        print(skip)
        return 0
    leagues = list(LEAGUES) if args.league == "all" else [args.league]
    client = PoliteClient()
    started = datetime.now(UTC)
    rows: list[dict] = []
    stats = pipeline.RunStats()
    for league in leagues:
        odds, st = pipeline.fetch_pregame_odds(EspnBasketball(client, league), args.days)
        rows += odds
        stats.merge(st)
    try:
        # brief API-server reads are waited out; a real writer (sync, backfill) wins
        db = Store(config.DB_PATH, lock_wait=10.0)
    except duckdb.IOException as e:
        if not is_lock_conflict(e):
            print(f"odds-snapshot: FAILED, cannot open the warehouse to write: {e}")
            return 1
        print(skip.replace("busy", "busy at write time"))
        return 0
    try:
        stats.odds = db.add_odds(rows)
        priced = sum(r.get("spread_home_price") is not None for r in rows)
        db.log_run(
            {
                "started_at": started,
                "finished_at": datetime.now(UTC),
                "command": "odds-snapshot " + ",".join(leagues),
                "network_requests": client.network_requests,
                "games_upserted": 0,
                "boxscores_upserted": 0,
                "errors": len(stats.errors),
                "notes": "; ".join(stats.errors[:20])
                or f"games_with_odds={len(rows)} with_prices={priced} new_rows={stats.odds}",
            }
        )
    finally:
        db.close()
    print(
        f"odds-snapshot: leagues={','.join(leagues)} games_with_odds={len(rows)} "
        f"with_prices={priced} new_rows={stats.odds} requests={client.network_requests} "
        f"errors={len(stats.errors)}"
    )
    for err in stats.errors[:10]:
        print(f"  error: {err}", file=sys.stderr)
    return 1 if stats.errors else 0


PRETIP_VERSION = "v1.1i"


def _pretip(args: argparse.Namespace) -> int:
    """Light pre-tip job (launchd, :20 and :50): for NBA games tipping between now + min_lead
    and now + window minutes, fetch a fresh summary per game (its injury report) without
    holding the lock, then in one short writer session store the pre-tip snapshots and write
    model v1.1i predictions for exactly those freshly captured games. A game whose summary
    shows it already started (or moved before the fetch) gets no prediction. Yields like
    odds-snapshot: a held writer lock prints one "skipped" line and exits 0."""
    from deepsports.analysis.record import injury_capture_teams, pretip_predictions_versions

    skip = "pretip: skipped, warehouse busy (another deepsports writer holds the lock)"
    try:
        busy = _warehouse_busy()
    except duckdb.IOException as e:
        print(f"pretip: FAILED, cannot open the warehouse: {e}")
        return 1
    if busy:
        print(skip)
        return 0
    started = datetime.now(UTC)
    lo = started + timedelta(minutes=args.min_lead)
    hi = started + timedelta(minutes=args.window_min)
    try:
        db = Store(config.DB_PATH, read_only=True, lock_wait=2.0)
    except duckdb.IOException as e:
        if not is_lock_conflict(e):
            print(f"pretip: FAILED, cannot open the warehouse: {e}")
            return 1
        print(skip)
        return 0
    try:
        window = db.games_for_injury_snapshot(lo, hi, league="nba")
    finally:
        db.close()
    game_ids = [g for g, _ in window]
    if not game_ids:
        print(
            f"pretip: no NBA games tipping in {args.min_lead}-{args.window_min} min; nothing to do"
        )
        return 0

    client = PoliteClient()
    src = EspnBasketball(client, "nba")
    reports, captures, stats = pipeline.fetch_injury_snapshots(src, game_ids, skip_started=True)
    captured = sorted({c["game_id"] for c in captures})
    try:
        # brief API-server reads are waited out; a real writer (sync, backfill) wins
        db = Store(config.DB_PATH, lock_wait=10.0)
    except duckdb.IOException as e:
        if not is_lock_conflict(e):
            print(f"pretip: FAILED, cannot open the warehouse to write: {e}")
            return 1
        print(skip.replace("busy", "busy at write time"))
        return 0
    written = fallback = 0
    try:
        stats.injuries = db.add_injuries(reports, captures)
        if captured:
            now = datetime.now(UTC)
            try:
                rows, _ = pretip_predictions_versions(
                    db.con, [PRETIP_VERSION], now=now, days=args.window_min / 1440 + 1, league="nba"
                )[PRETIP_VERSION]
            except ValueError as e:  # e.g. no completed games to train on
                stats.errors.append(f"predict {PRETIP_VERSION}: {e}")
                rows = []
            rows = [r for r in rows if r["game_id"] in set(captured)]
            written = db.add_predictions(rows) if rows else 0
            teams = injury_capture_teams(db.con, [r["game_id"] for r in rows])
            fallback = 2 * len(rows) - sum(len(teams.get(r["game_id"], ())) for r in rows)
        summary = (
            f"games={len(game_ids)} captured={len(captured)} predicted={written} "
            f"fallback_teams={fallback} skipped_started={stats.skipped_started}"
        )
        db.log_run(
            {
                "started_at": started,
                "finished_at": datetime.now(UTC),
                "command": f"pretip {PRETIP_VERSION}",
                "network_requests": client.network_requests,
                "games_upserted": written,
                "boxscores_upserted": 0,
                "errors": len(stats.errors),
                "notes": "; ".join([summary, *stats.errors[:20]]),
            }
        )
    finally:
        db.close()
    print(
        f"pretip: {summary} injuries={stats.injuries} requests={client.network_requests} "
        f"errors={len(stats.errors)}"
    )
    for err in stats.errors[:10]:
        print(f"  error: {err}", file=sys.stderr)
    return 1 if stats.errors else 0


def _prices_backfill(args: argparse.Namespace) -> int:
    """Offline price backfill (no network): list rows with NULL prices (read-only), re-parse
    their cached responses without holding the lock, then fill the prices in one short write.
    Idempotent: the write re-checks that each row's line is unchanged and prices still NULL."""
    leagues = list(LEAGUES) if args.league == "all" else [args.league]
    started = datetime.now(UTC)
    db = Store(config.DB_PATH, read_only=True, lock_wait=120.0)
    try:
        todo = {lg: db.odds_missing_prices(lg) for lg in leagues}
    finally:
        db.close()
    fills: list[dict] = []
    summary: list[str] = []
    notes: list[str] = []
    for league in leagues:
        f, counts, n = pipeline.plan_price_backfill(todo[league], config.RAW_DIR, league)
        fills += f
        notes += n
        summary.append(
            f"{league}: rows={len(todo[league])} "
            + " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        )
    changed = 0
    if not args.dry_run:
        db = Store(config.DB_PATH, lock_wait=120.0)
        try:
            changed = db.fill_odds_prices(fills)
            db.log_run(
                {
                    "started_at": started,
                    "finished_at": datetime.now(UTC),
                    "command": "prices-backfill " + ",".join(leagues),
                    "network_requests": 0,
                    "games_upserted": 0,
                    "boxscores_upserted": 0,
                    "errors": 0,
                    "notes": f"{'; '.join(summary)}; rows_updated={changed}",
                }
            )
        finally:
            db.close()
    print(f"prices-backfill{' (dry run)' if args.dry_run else ''}: " + "; ".join(summary))
    print(f"  matched_with_prices={len(fills)} rows_updated={changed}")
    for note in notes[:10]:
        print(f"  mismatch: {note}")
    return 0


def _predict(args: argparse.Namespace, db: Store) -> int:
    """Train the league's model on all completed games and upsert a prediction for every game
    that hasn't tipped off yet (one row per game/model/version: the latest pre-tip
    prediction). College: D1-vs-D1 games past each version's games-played gate.
    `--model-version` takes a comma-separated list (college: `all` = every version); college
    versions sharing a model are fit once."""
    from deepsports.analysis.record import DEFAULT_VERSIONS, pretip_predictions_versions

    started = datetime.now(UTC)
    spec = args.model_version or DEFAULT_VERSIONS[args.league]
    versions = [v.strip() for v in spec.split(",") if v.strip()]
    if args.league == "ncaab":
        from deepsports.analysis.ncaab import VERSIONS

        if versions == ["all"]:
            versions = list(VERSIONS)
        bad = [v for v in versions if v not in VERSIONS]
        if bad or not versions:
            msg = (
                f"error: unknown college model version {', '.join(bad) or spec!r} "
                f"(use {', '.join(VERSIONS)} or all)"
            )
            print(msg, file=sys.stderr)
            return 2
    errors: list[str] = []
    results: dict[str, tuple[list, int]] = {}
    gated: dict[str, dict[str, int]] = {}
    try:
        results = pretip_predictions_versions(
            db.con, versions, now=started, days=args.days, league=args.league, gated=gated
        )
    except ValueError as e:  # e.g. no completed games to train on
        errors.append(f"predict: {e}")
    for version in versions:
        rows, skipped = results.get(version, ([], 0))
        written = db.add_predictions(rows) if rows else 0
        gate = "".join(f" skipped_{k}={v}" for k, v in sorted(gated.get(version, {}).items()))
        db.log_run(
            {
                "started_at": started,
                "finished_at": datetime.now(UTC),
                "command": " ".join(sys.argv[1:]) or args.command,
                "network_requests": 0,
                "games_upserted": written,
                "boxscores_upserted": 0,
                "errors": len(errors),
                "notes": "; ".join(errors)
                or f"predictions={written} league={args.league} model_version={version} "
                f"skipped_started={skipped}{gate}",
            }
        )
        print(
            f"predict: league={args.league} model_version={version} "
            f"predictions={written} skipped_started={skipped}{gate} errors={len(errors)}"
        )
    for err in errors:
        print(f"  error: {err}", file=sys.stderr)
    return 1 if errors else 0


def _paper_log(args: argparse.Namespace, db: Store) -> int:
    """Log the frozen paper-trade rules' bets for games that haven't started (analysis/paper.py).
    Never updates a bet already logged."""
    from deepsports.analysis.paper import log_bets

    started = datetime.now(UTC)
    errors: list[str] = []
    stats: dict = {}
    try:
        stats = log_bets(db, now=started, days=args.days)
    except (ValueError, duckdb.Error) as e:
        errors.append(f"paper log: {e}")
    new = sum(v["new"] for v in stats.values())
    parts = [f"{rule}: new={v['new']}/{v['qualifying']}" for rule, v in stats.items()]
    db.log_run(
        {
            "started_at": started,
            "finished_at": datetime.now(UTC),
            "command": " ".join(sys.argv[1:]) or "paper log",
            "network_requests": 0,
            "games_upserted": new,
            "boxscores_upserted": 0,
            "errors": len(errors),
            "notes": "; ".join(errors) or "; ".join(parts),
        }
    )
    for rule, v in stats.items():
        skipped = " ".join(f"{k}={n}" for k, n in sorted(v["skipped"].items()))
        print(f"paper log: {rule} new={v['new']} qualifying={v['qualifying']} {skipped}".rstrip())
    for err in errors:
        print(f"  error: {err}", file=sys.stderr)
    return 1 if errors else 0


def _attach_predictions(db: Store, rows: list[dict]) -> None:
    """Add `prediction` (API Prediction object or None) to each upcoming row, from the latest
    model-v1 prediction. Upcoming games haven't started, so any stored row is pre-tip. Early-season
    college predictions (`ncaab-v1-early`) and side-by-side versions (`ncaab-v1p`,
    config.HIDDEN_MODEL_VERSIONS) and the injury-aware NBA `v1.1i` (all in
    config.CALENDAR_EXCLUDED_VERSIONS) are left out: the calendar only gets the display one."""
    from deepsports.analysis.model import MODEL_NAME
    from deepsports.analysis.record import prediction_card

    preds = {}
    if db.has_table("predictions"):
        for p in db.latest_predictions(
            (r["game_id"] for r in rows),
            include_early=False,
            exclude_versions=config.CALENDAR_EXCLUDED_VERSIONS,
        ):
            if p["model"] == MODEL_NAME:
                preds[p["game_id"]] = p
    for r in rows:
        p = preds.get(r["game_id"])
        r["prediction"] = prediction_card(p, r["home_abbr"], r["away_abbr"]) if p else None


def _ensemble_bets(args: argparse.Namespace, db: Store) -> int:
    from deepsports.analysis import ensemble_bets as eb

    if args.ensemble_command == "grade":
        print(json.dumps(eb.grade_runs(db.con), indent=1))
        return 0
    if args.agents < 1 or args.days < 1:
        print("error: --agents and --days must be >= 1", file=sys.stderr)
        return 2
    now = datetime.now(UTC)
    leagues = list(LEAGUES) if args.league == "all" else [args.league]
    slate = eb.load_slate(db.con, now, days=args.days, leagues=leagues, context=args.context)
    if args.manualbets:
        from deepsports.analysis.manualbets_context import attach_manualbets, load_export

        export = None
        if args.manualbets != "none":
            try:
                export = load_export(Path(args.manualbets))
            except (OSError, ValueError) as err:
                print(f"warning: ManualBets export unreadable: {err}", file=sys.stderr)
        attach_manualbets(slate, export)
    if args.tag:
        slate["context_version"] += args.tag
    run = eb.new_run_dir(now)
    paths = eb.write_context(run, slate, args.agents, seed=args.seed)
    print(
        json.dumps(
            {
                "run": str(run),
                "games": len(slate["games"]),
                "unlined_games": slate["unlined_games"],
                "contexts": {p.stem.removeprefix("context-"): str(p) for p in paths},
            },
            indent=1,
        )
    )
    return 0


def _model_picks(args: argparse.Namespace, db: Store) -> int:
    from deepsports.analysis import ensemble_bets as eb
    from deepsports.analysis import model_picks as mp
    from deepsports.analysis.manualbets_context import attach_manualbets, load_export

    if args.picks_command == "grade":
        if args.slates:
            runs = []
            for f in map(Path, args.slates):
                slate = json.loads(f.read_text())
                if not (slate.get("manualbets") or {}).get("available"):
                    print(f"skip {f}: no ManualBets numbers", file=sys.stderr)
                    continue
                runs.append(mp.slate_run(slate, run=f.parent.name))
            print(json.dumps(mp.grade_picks(db.con, runs), indent=1))
        else:
            print(json.dumps(mp.grade_runs(db.con), indent=1))
        return 0
    if args.days < 1:
        print("error: --days must be >= 1", file=sys.stderr)
        return 2
    now = datetime.now(UTC)
    leagues = list(LEAGUES) if args.league == "all" else [args.league]
    slate = eb.load_slate(db.con, now, days=args.days, leagues=leagues)
    export = None
    if args.manualbets != "none":
        try:
            export = load_export(Path(args.manualbets))
        except (OSError, ValueError) as err:
            print(f"warning: ManualBets export unreadable: {err}", file=sys.stderr)
    attach_manualbets(slate, export)
    run, text = mp.write_run(slate, now)
    print(text)
    print(f"run: {run}", file=sys.stderr)
    return 0


def _read_commands(args: argparse.Namespace, db: Store) -> int:
    if args.command == "ensemble-bets":
        return _ensemble_bets(args, db)
    if args.command == "model-picks":
        return _model_picks(args, db)
    if args.command == "paper":
        from deepsports.analysis.paper import paper_report, render_report, report_json

        report = paper_report(db.con)
        print(report_json(report) if args.json else render_report(report))
        return 0
    if args.command == "check":
        from deepsports.quality import run_checks

        hard_fail = False
        for c in run_checks(db):
            mark = "ok  " if c.failures == 0 else ("FAIL" if c.hard else "warn")
            hard_fail |= c.hard and c.failures > 0
            print(f"{mark}  {c.name}: {c.detail}")
        return 1 if hard_fail else 0
    if args.command == "status":
        for table, n in db.counts().items():
            print(f"{table:20s} {n}")
        for league, n in db.con.execute(
            "SELECT league, count(*) FROM games GROUP BY 1 ORDER BY 1"
        ).fetchall():
            print(f"games[{league}]{'':{max(0, 12 - len(league))}s} {n}")
        rows = db.con.execute(
            "SELECT started_at, command, network_requests, games_upserted, boxscores_upserted, "
            "errors FROM ingest_runs ORDER BY started_at DESC LIMIT 5"
        ).fetchall()
        for r in rows:
            print("run", *r)
        return 0

    cfg = load_calendar_config()
    days = args.days or cfg.get("days_ahead", 7)
    leagues = list(LEAGUES) if args.league == "all" else [args.league]
    rows = []
    for league in leagues:
        teams = None
        if args.teams:
            teams = [t.strip().upper() for t in args.teams.split(",") if t.strip()]
        elif not args.all:
            teams = followed_teams(cfg, league) or None
            if teams is None and league != "nba":
                continue  # an empty college follow list means none, not all ~6,000 games
        rows += pipeline.upcoming(db, days, teams, league)
    rows.sort(key=lambda r: (r["start_time_utc"], r["game_id"]))
    if args.json:
        _attach_predictions(db, rows)
        print(json.dumps(rows, indent=2, default=str))
    else:
        for r in rows:
            odds = f"  [{r['odds_details']}, O/U {r['over_under']}]" if r["odds_details"] else ""
            tv = f"  TV: {r['broadcasts']}" if r["broadcasts"] else ""
            print(f"{r['start_local'][:16].replace('T', ' ')}  {r['title']}{odds}{tv}")
        print(f"{len(rows)} games in the next {days} days", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
