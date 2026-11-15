"""`deepsports books grab`: fetch each book's lines from OddsPapi, match them to warehouse games and
write `<BOOKS_DIR>/<book>/<YYYY-MM-DD>.json` in the Circa lines contract (docs/API.md, Circa):

    {"date", "grabbed_at", "book", "source": "oddspapi", "source_book": "<slug>",
     "lines": [{"game_id", "league", "away", "home", "market", "side", "line", "price",
                "rotation": null}]}

`--early` (the 21:00 evening run) writes the same contract to
`<BOOKS_DIR>/<book>/early/<YYYY-MM-DD>.json` for the next day's games instead, so the day file the
picks read is never touched; its `grabbed_at` timestamps the night-before line.

About 2 requests per run (one per book) plus 1 when the market catalogue needs a refresh. A line
whose game can't be matched (no warehouse game with both teams within 6 h of the start) is left
out, because the feed doesn't say which team is home. Never needs the writer lock: one brief
read-only open to load the candidate games.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from deepsports import config
from deepsports.books import BOOKS, oddspapi
from deepsports.circa.lines import FIELDS, validate_line
from deepsports.circa.match import load_candidates, match_game
from deepsports.circa.storage import require_mounted, today
from deepsports.http import PoliteClient

MAX_START_GAP = timedelta(hours=6)


def lines_path(book: str, day: date, early: bool = False) -> Path:
    return config.BOOKS_DIR / book / ("early" if early else "") / f"{day.isoformat()}.json"


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("lines"), list) else None


def load(book: str, day: date | None = None) -> dict | None:
    """The day's grabbed lines for `book`, or None if missing or unreadable."""
    return _read(lines_path(book, day or today()))


def load_early(book: str, day: date) -> dict | None:
    """The night-before (`grab --early`) lines for `book`'s games on `day`, or None."""
    return _read(lines_path(book, day, early=True))


def tomorrow() -> date:
    return today() + timedelta(days=1)


def _start(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def _near(cands: Sequence[Mapping], start: datetime | None) -> list[Mapping]:
    if start is None:
        return list(cands)
    out = []
    for g in cands:
        gs = _start(g.get("start_time_utc"))
        if gs is not None and gs.tzinfo is None:
            gs = gs.replace(tzinfo=start.tzinfo)
        if gs is None or abs(gs - start) <= MAX_START_GAP:
            out.append(g)
    return out


def _local_day(v: Any) -> date | None:
    s = _start(v)
    if s is None:
        return None
    return (s if s.tzinfo else s.replace(tzinfo=UTC)).astimezone(config.LOCAL_TZ).date()


_SIDE = {("1", False): "home", ("2", False): "away", ("1", True): "away", ("2", True): "home"}


def to_lines(rows: Sequence[Mapping[str, Any]], candidates: Sequence[Mapping]):
    """(lines in the Circa contract, oriented to the warehouse game; unmatched fixture count).
    Pure. Participant 1 is tried as home first; `match_game` flips it when the names say so."""
    by_fixture: dict[str, list[Mapping]] = {}
    for r in rows:
        by_fixture.setdefault(r["fixture_id"], []).append(r)
    lines, unmatched = [], 0
    for rs in by_fixture.values():
        r0 = rs[0]
        cands = _near(candidates, _start(r0["start_time"]))
        game, swapped = match_game(r0["p2"] or "", r0["p1"] or "", cands, r0["league"])
        if game is None:
            unmatched += 1
            continue
        home, away = (r0["p2"], r0["p1"]) if swapped else (r0["p1"], r0["p2"])
        for r in rs:
            side = r["who"] if r["market"] == "total" else _SIDE[(r["who"], swapped)]
            raw = {"league": game["league"], "away": away, "home": home, "market": r["market"],
                   "side": side, "line": r["line"], "price": r["price"]}  # fmt: skip
            ln, _why = validate_line(raw)
            if ln is None:
                continue
            ln["game_id"] = game["game_id"]
            ln["league"] = game["league"]
            lines.append({k: ln[k] for k in FIELDS})
    lines.sort(key=lambda q: (q["game_id"], q["market"], q["side"]))
    return lines, unmatched


@dataclass
class GrabResult:
    ok: bool
    message: str
    counts: dict[str, int] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


def _write(path: Path, data: dict) -> None:
    require_mounted(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=1) + "\n")
    os.replace(tmp, path)


def grab_day(
    day: date | None = None,
    books: Mapping[str, str] = BOOKS,
    client: PoliteClient | None = None,
    key: str | None = None,
    candidates: Callable[[date], list[dict]] = load_candidates,
    early: bool = False,
) -> GrabResult:
    """Grab `books` for `day`. With `early`, write the early file instead of the day file and keep
    only games that tip on `day` (local); `day` then defaults to tomorrow."""
    day = day or (tomorrow() if early else today())
    now = datetime.now(config.LOCAL_TZ)
    label = f"books early {day}" if early else f"books {day}"
    try:
        key = key or oddspapi.read_key()
    except oddspapi.OddsPapiError as e:
        return GrabResult(False, f"{label}: FAILED, {e}")
    if client is None:
        raw = require_mounted(config.BOOKS_DIR) / "raw"
        client = PoliteClient(raw_dir=raw, min_interval=oddspapi.MIN_INTERVAL, max_retries=1)
    try:
        cands = candidates(day)
    except Exception as e:  # warehouse busy: without games we can't tell home from away
        return GrabResult(False, f"{label}: FAILED, no games to match ({type(e).__name__})")
    # The candidate window runs into the next day; a night-before file holds `day`'s games only.
    keep = {g["game_id"] for g in cands if _local_day(g.get("start_time_utc")) == day}
    res = GrabResult(True, "")
    refreshed = False
    try:
        markets = oddspapi.fetch_markets(client, key)
    except oddspapi.OddsPapiError as e:
        return GrabResult(False, f"{label}: FAILED, market catalogue: {e}")
    parts = []
    for book, slug in books.items():
        try:
            tag = f"early-{slug}" if early else slug
            fixtures = oddspapi.fetch_book(client, key, slug, f"{day}/{tag}-{now:%H%M%S}")
            if oddspapi.unknown_markets(fixtures, slug, markets) and not refreshed:
                markets, refreshed = oddspapi.fetch_markets(client, key, refresh=True), True
        except oddspapi.OddsPapiError as e:
            res.ok = False
            res.problems.append(f"{book}: {e}")
            parts.append(f"{book} FAILED")
            continue
        rows = oddspapi.parse_fixtures(fixtures, slug, oddspapi.market_index(markets))
        lines, unmatched = to_lines(rows, cands)
        if early:
            lines = [q for q in lines if q["game_id"] in keep]
        _write(lines_path(book, day, early), {
            "date": day.isoformat(),
            "grabbed_at": now.isoformat(timespec="seconds"),
            "book": book,
            "source": "oddspapi",
            "source_book": slug,
            "lines": lines,
        })  # fmt: skip
        games = len({q["game_id"] for q in lines})
        res.counts[book] = len(lines)
        parts.append(f"{book} {len(lines)} lines ({games} games" +
                     (f", {unmatched} unmatched)" if unmatched else ")"))  # fmt: skip
    res.message = f"{label}: " + ", ".join(parts) + f"; {client.network_requests} requests"
    return res
