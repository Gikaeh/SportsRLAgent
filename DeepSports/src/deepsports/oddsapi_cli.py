"""`deepsports odds-api-history plan|probe|pull|status|live`: The Odds API historical snapshots
and the scheduled live capture.

Files only, never DuckDB: gzipped responses under
RAW_DIR/oddsapi/historical/<sport>/<markets>/<regions>/<UTC stamp>.json.gz plus a credit ledger
(ledger.jsonl) beside them. Game days come from the ESPN scoreboard cache (or season windows when
a season isn't cached). `pull` is resumable (cached timestamps are skipped), stops before the
account's remaining credits fall below --reserve, and fetches the first --times entry for every
game day before the next one, so a short run still completes the night-before snapshots.

`live` (launchd com.deepsports.oddsapi-live, tools/oddsapi-live.sh) saves one envelope per league
per 30-minute slot to RAW_DIR/oddsapi/live/<sport>/<UTC slot>.json.gz with its own ledger
(oddsapi/live/ledger.jsonl). It prints one line, spends nothing when the slot is already saved,
and exits 0 without fetching when past --until, under --reserve, without a key, with a rejected
key, or when the data dir is unavailable."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, date, datetime
from typing import Any

from deepsports import config
from deepsports.http import PoliteClient
from deepsports.sources import oddsapi_history as oah

log = logging.getLogger(__name__)
DEFAULT_TIMES = "-1@21:00,0@09:00"
LIVE_UNTIL = date(2026, 12, 24)  # the owner's key's month ends about 2026-12-23
LIVE_RESERVE = 2000


def _csv(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


def _add_plan_args(p: argparse.ArgumentParser, *, times: str = DEFAULT_TIMES) -> None:
    p.add_argument(
        "--league", choices=sorted(oah.SPORTS), action="append", help="default: ncaab and nba"
    )
    p.add_argument("--season", type=int, action="append", help="season end year (2022 = 2021-22)")
    p.add_argument("--markets", type=_csv, default=["totals", "spreads"], help="totals,spreads")
    p.add_argument("--regions", type=_csv, default=["us", "eu"], help="us,eu")
    p.add_argument(
        "--bookmakers",
        type=_csv,
        default=None,
        help="book keys from any region instead of --regions; every 10 bill as one region",
    )
    p.add_argument(
        "--times",
        default=times,
        help="snapshots per game day as <day offset>@<HH:MM Pacific>, comma-separated "
        f"(default {times}: 21:00 PT the night before, 09:00 PT game-day morning)",
    )
    p.add_argument("--extra-times", default="", help="more <offset>@<HH:MM>, e.g. -1@18:00")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="deepsports odds-api-history", description=__doc__)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("plan", help="list the snapshot timestamps and the credit cost (offline)")
    _add_plan_args(pl)
    pl.add_argument("--list", action="store_true", help="print every timestamp")

    pr = sub.add_parser("probe", help="small capped run: night-before coverage on sample days")
    _add_plan_args(pr, times="-1@21:00")
    pr.add_argument("--samples", type=int, default=5, help="game days, spread over the seasons")
    pr.add_argument("--max-credits", type=int, default=100)
    pr.add_argument("--reserve", type=int, default=0, help="never go below this many credits")
    pr.set_defaults(markets=["totals"])

    pu = sub.add_parser("pull", help="resumable bulk pull of the plan (cached ones skipped)")
    _add_plan_args(pu)
    pu.add_argument("--reserve", type=int, required=True, help="stop above this many credits")
    pu.add_argument("--max-credits", type=int, default=None, help="cap for this run")
    pu.add_argument("--limit", type=int, default=None, help="at most this many requests")
    pu.add_argument("--dry-run", action="store_true", help="show what would be fetched")

    sub.add_parser("status", help="cached snapshots per sport/markets/regions + credits used")

    lv = sub.add_parser(
        "live",
        help="capture live lines now (1 credit per market x region per league; one output line)",
    )
    lv.add_argument(
        "--league", choices=sorted(oah.SPORTS), action="append", help="default: ncaab and nba"
    )
    lv.add_argument("--markets", type=_csv, default=["totals", "spreads"])
    lv.add_argument(
        "--bookmakers",
        type=_csv,
        default=None,
        help=f"default: the {len(oah.LIVE_BOOKMAKERS)} capture books (one billing region)",
    )
    lv.add_argument("--regions", type=_csv, default=None, help="regions instead of the books")
    lv.add_argument(
        "--reserve",
        type=int,
        default=LIVE_RESERVE,
        help=f"skip a league when it would leave fewer credits (default {LIVE_RESERVE})",
    )
    lv.add_argument(
        "--until",
        type=date.fromisoformat,
        default=LIVE_UNTIL,
        help=f"do nothing after this Pacific date (default {LIVE_UNTIL})",
    )
    lv.add_argument("--slot-minutes", type=int, default=30, help="file slot width (default 30)")
    lv.add_argument("--force", action="store_true", help="refetch a slot that is already saved")
    return p


# ---------------------------------------------------------------- planning


def _plan(args: argparse.Namespace) -> list[dict[str, Any]]:
    """[{league, sport, season, source, days, times: [(spec_index, ts, game_day)]}]"""
    specs = oah.parse_times(args.times)
    if args.extra_times:
        specs += oah.parse_times(args.extra_times)
    leagues = args.league or ["ncaab", "nba"]
    out = []
    for league in leagues:
        seasons = args.season or oah.DEFAULT_SEASONS[league]
        cached = oah.scoreboard_game_days(config.RAW_DIR / "espn" / league / "scoreboard")
        for season, (days, source) in oah.game_days(league, seasons, cached).items():
            stamps: dict[datetime, tuple[int, date]] = {}
            for i, spec in enumerate(specs):
                for d in days:
                    for ts in oah.snapshot_times([d], [spec]):
                        stamps.setdefault(ts, (i, d))
            out.append(
                {
                    "league": league,
                    "sport": oah.SPORTS[league],
                    "season": season,
                    "source": source,
                    "days": days,
                    "times": sorted((i, ts, d) for ts, (i, d) in stamps.items()),
                }
            )
    return out


def _cost(args: argparse.Namespace, n: int) -> int:
    return oah.cost(n, args.markets, args.regions, args.bookmakers)


def _cached(sport: str, args: argparse.Namespace, ts: datetime) -> bool:
    return oah.cache_path(
        sport, args.markets, args.regions, ts, bookmakers=args.bookmakers
    ).exists()


def _cmd_plan(args: argparse.Namespace) -> int:
    plan = _plan(args)
    per = _cost(args, 1)
    print(
        f"markets={','.join(args.markets)} {oah.scope_label(args.regions, args.bookmakers)} "
        f"times={args.times}{',' + args.extra_times if args.extra_times else ''} "
        f"-> {per} credits per snapshot"
    )
    total_n = total_todo = 0
    for s in plan:
        n = len(s["times"])
        todo = sum(not _cached(s["sport"], args, ts) for _, ts, _ in s["times"])
        total_n += n
        total_todo += todo
        first, last = (s["days"][0], s["days"][-1]) if s["days"] else ("-", "-")
        print(
            f"{s['league']:5s} {s['season'] - 1}-{s['season'] % 100:02d}  {len(s['days']):3d} "
            f"game days ({s['source']:6s} {first} .. {last})  {n:4d} snapshots  "
            f"{_cost(args, n):7,d} credits  ({todo} not cached)"
        )
        if args.list:
            for _, ts, d in s["times"]:
                print(f"    {oah.iso(ts)}  for game day {d}")
    print(
        f"total: {total_n} snapshots, {_cost(args, total_n):,d} credits;"
        f" still to fetch {total_todo} = {_cost(args, total_todo):,d}"
    )
    return 0


# ---------------------------------------------------------------- fetching


def _report(credits: oah.Credits) -> str:
    return f"credits last={credits.last} used={credits.used} remaining={credits.remaining}"


def _fetch_one(
    client: PoliteClient,
    key: str,
    sport: str,
    ts: datetime,
    args: argparse.Namespace,
    game_day: date,
) -> tuple[dict[str, Any], oah.Credits]:
    data, credits = oah.fetch_historical(
        client, key, sport, ts, args.markets, args.regions, args.bookmakers
    )
    oah.write_cached(
        oah.cache_path(sport, args.markets, args.regions, ts, bookmakers=args.bookmakers), data
    )
    oah.append_ledger(
        {
            "fetched_at": oah.iso(datetime.now(UTC)),
            "sport": sport,
            "markets": ",".join(args.markets),
            "scope": oah.scope_label(args.regions, args.bookmakers),
            "requested": oah.iso(ts),
            "game_day": game_day.isoformat(),
            "snapshot": data.get("timestamp"),
            "events": len(data.get("data") or []),
            "last": credits.last,
            "used": credits.used,
            "remaining": credits.remaining,
        }
    )
    return data, credits


def _run(
    args: argparse.Namespace,
    queue: list[tuple[str, datetime, date]],
    *,
    reserve: int,
    max_credits: int | None,
    limit: int | None = None,
    on_snapshot=None,
) -> int:
    per = _cost(args, 1)
    todo = [(sp, ts, d) for sp, ts, d in queue if not _cached(sp, args, ts)]
    print(f"{len(queue)} snapshots planned, {len(queue) - len(todo)} cached, {len(todo)} to fetch")
    if getattr(args, "dry_run", False):
        print(f"dry run: up to {_cost(args, len(todo)):,d} credits")
        for sp, ts, d in todo[:20]:
            print(f"  {sp} {oah.iso(ts)} (game day {d})")
        return 0
    if on_snapshot:  # report cached ones too
        for sp, ts, d in queue:
            if _cached(sp, args, ts):
                on_snapshot(
                    sp,
                    ts,
                    d,
                    oah.read_cached(
                        oah.cache_path(
                            sp, args.markets, args.regions, ts, bookmakers=args.bookmakers
                        )
                    ),
                )
    if not todo:
        return 0
    key = oah.read_key()
    client = PoliteClient()
    credits = oah.check_quota(client, key)
    print(f"start: {_report(credits)}")
    remaining = credits.remaining
    spent = fetched = 0
    status = 0
    for sp, ts, d in todo:
        if remaining is not None and remaining - per < reserve:
            print(f"stop: {remaining} remaining, next call costs {per}, reserve {reserve}")
            break
        if max_credits is not None and spent + per > max_credits:
            print(f"stop: run cap of {max_credits} credits reached ({spent} spent)")
            break
        if limit is not None and fetched >= limit:
            print(f"stop: request limit {limit} reached")
            break
        try:
            data, credits = _fetch_one(client, key, sp, ts, args, d)
        except oah.OddsApiError as e:
            print(f"error: {sp} {oah.iso(ts)}: {e}", file=sys.stderr)
            status = 1
            break
        fetched += 1
        spent += credits.last if credits.last is not None else per
        remaining = credits.remaining
        print(
            f"{sp} {oah.iso(ts)} -> snapshot {data.get('timestamp')} "
            f"{len(data.get('data') or [])} events  {_report(credits)}"
        )
        if on_snapshot:
            on_snapshot(sp, ts, d, data)
    print(f"done: {fetched} fetched, {spent} credits spent, remaining {remaining}")
    return status


def _cmd_pull(args: argparse.Namespace) -> int:
    queue = sorted(
        ((i, s["sport"], ts, d) for s in _plan(args) for i, ts, d in s["times"]),
        key=lambda x: (x[0], x[1], x[2]),
    )
    return _run(
        args,
        [(sp, ts, d) for _, sp, ts, d in queue],
        reserve=args.reserve,
        max_credits=args.max_credits,
        limit=args.limit,
    )


def _cmd_probe(args: argparse.Namespace) -> int:
    rows = [(s["sport"], ts, d) for s in _plan(args) for _, ts, d in s["times"]]
    rows.sort(key=lambda x: (x[1], x[0]))
    n = min(args.samples, len(rows))
    picks = [rows[round(i * (len(rows) - 1) / max(n - 1, 1))] for i in range(n)] if n else []

    def show(sp: str, ts: datetime, d: date, data: Any) -> None:
        for market in args.markets:
            cov = oah.coverage(data, d, market)
            books = ", ".join(f"{b}={c}" for b, c in list(cov["per_book"].items())[:8])
            print(
                f"  coverage {sp} {d} @ {oah.iso(ts)} {market}: {cov['with_market']}/"
                f"{cov['events']} events  [{books}]"
            )

    return _run(args, picks, reserve=args.reserve, max_credits=args.max_credits, on_snapshot=show)


def _live_scope(args: argparse.Namespace) -> tuple[list[str], list[str] | None]:
    """(regions, bookmakers): --regions alone means regions; otherwise the capture books."""
    if args.regions and not args.bookmakers:
        return args.regions, None
    return ["us"], args.bookmakers or list(oah.LIVE_BOOKMAKERS)


def _cmd_live(args: argparse.Namespace, now: datetime | None = None) -> int:
    """One output line. Exit 0 unless a fetch failed for a reason other than the key."""
    now = now or datetime.now(UTC)
    head = f"oddsapi live {oah.iso(now)}:"
    if now.astimezone(oah.PT).date() > args.until:
        print(f"{head} skipped, past --until {args.until}")
        return 0
    regions, books = _live_scope(args)
    per = oah.live_cost(args.markets, regions, books)
    slot = oah.live_slot(now, args.slot_minutes)
    leagues = args.league or ["ncaab", "nba"]
    todo = [lg for lg in leagues if args.force or not oah.live_path(oah.SPORTS[lg], slot).exists()]
    if not todo:
        print(f"{head} slot {oah.file_stamp(slot)} already saved for {','.join(leagues)}")
        return 0
    try:
        key = oah.read_key()
    except oah.OddsApiError as e:
        print(f"{head} skipped, {e}")
        return 0
    client = PoliteClient()
    try:
        remaining = oah.check_quota(client, key).remaining
    except oah.OddsApiError as e:
        if e.status in (401, 403):
            print(f"{head} skipped, key rejected (HTTP {e.status}: missing, expired or no credits)")
            return 0
        print(f"{head} error checking quota: {e}")
        return 1
    parts, status, spent = [], 0, 0
    for lg in todo:
        sport = oah.SPORTS[lg]
        if remaining is not None and remaining - per < args.reserve:
            parts.append(f"{lg} skipped (reserve {args.reserve}, {remaining} left)")
            continue
        fetched_at = datetime.now(UTC)  # the request time: taken right before the call
        try:
            data, credits = oah.fetch_live(client, key, sport, args.markets, regions, books)
        except oah.OddsApiError as e:
            if e.status in (401, 403):
                parts.append(f"{lg} skipped, key rejected (HTTP {e.status})")
                break
            parts.append(f"{lg} error {e}")
            status = 1
            continue
        path = oah.live_path(sport, slot)
        oah.write_cached(
            path, oah.live_envelope(data, fetched_at, sport, args.markets, regions, books, credits)
        )
        n_rows = len(oah.parse_snapshot(data, fetched_at))
        oah.append_ledger(
            {
                "fetched_at": oah.iso(fetched_at),
                "snapshot_ts": oah.iso(fetched_at),  # request time (pre-registration 2026-11-23)
                "slot": oah.iso(slot),
                "sport": sport,
                "markets": ",".join(args.markets),
                "scope": oah.scope_label(regions, books),
                "file": path.name,
                "events": len(data),
                "rows": n_rows,
                "last": credits.last,
                "used": credits.used,
                "remaining": credits.remaining,
            },
            subdir=oah.LIVE_SUBDIR,
        )
        spent += credits.last if credits.last is not None else per
        if credits.remaining is not None:
            remaining = credits.remaining
        parts.append(f"{lg} {len(data)} events {n_rows} rows")
    print(f"{head} {'; '.join(parts)}; spent {spent}, remaining {remaining}")
    return status


def _cmd_status() -> int:
    base = config.RAW_DIR / oah.RAW_SUBDIR
    combos = sorted({p.parent for p in base.glob("*/*/*/*.json.gz")}) if base.exists() else []
    if not combos:
        print(f"no cached snapshots under {base}")
    for c in combos:
        files = sorted(c.glob("*.json.gz"))
        rel = c.relative_to(base)
        print(f"{rel}: {len(files)} snapshots  {files[0].name[:16]} .. {files[-1].name[:16]}")
    ledger = oah.read_ledger()
    spent = sum(e.get("last") or 0 for e in ledger)
    last = ledger[-1] if ledger else {}
    print(
        f"ledger: {len(ledger)} calls, {spent:,d} credits spent; last remaining "
        f"{last.get('remaining')} at {last.get('fetched_at')}"
    )
    return 0


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    try:
        config.require_data_dir()
    except config.DataDirUnavailable as e:
        if args.cmd == "live":  # scheduled: one line, not a failure
            print(f"oddsapi live: skipped, data dir unavailable ({e})")
            return 0
        print(f"error: {e}", file=sys.stderr)
        return 2
    try:
        if args.cmd == "plan":
            return _cmd_plan(args)
        if args.cmd == "probe":
            return _cmd_probe(args)
        if args.cmd == "pull":
            return _cmd_pull(args)
        if args.cmd == "live":
            return _cmd_live(args)
        return _cmd_status()
    except oah.OddsApiError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except OSError as e:  # e.g. the drive went away mid-run
        if args.cmd == "live":
            print(f"oddsapi live: error {type(e).__name__}: {e}")
            return 1
        raise
