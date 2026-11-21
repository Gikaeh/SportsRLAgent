"""cbbdata (https://www.cbbdata.com, Andrew Weatherman's API over Barttorvik T-Rank): the daily
T-Rank ratings archive for men's D1, one Parquet file per season.

- GET /api/torvik/ratings/archive?year=<season end year>&key=<key> returns Parquet with one row
  per team per rating day: rank, team, conf, record, barthag, adj_o, adj_d, adj_tempo, wab (+ *_rk),
  proj_record, date, year, ... (fixture: tests/fixtures/cbbdata_torvik_archive_2022_trim.parquet).
- Coverage (checked 2026-11-19): seasons 2015-2025. 2026 and 2027 come back as empty Parquet
  (cbbdata stopped updating after 2024-25; its GitHub issue "No Bart Torvik Data for 2025-26").
- Date semantics (checked 2026-11-19 against cached ESPN finals, 2022/2024/2025): a row dated D
  already includes the games of ESPN game day D (an end-of-day snapshot). Leak-free join for a
  game on day D: the latest row with `as_of_date <= D - 1 day`.

Fetching never touches DuckDB's warehouse; the parser opens only an in-memory DuckDB to read the
Parquet. The key is read from `config.CBBDATA_KEY_FILE` at run time and never logged: it rides in
the query string, so request URLs are never logged either.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from deepsports import config
from deepsports.http import FetchError, PoliteClient

URL = "https://www.cbbdata.com/api/torvik/ratings/archive"
FIRST_SEASON = 2015  # 2014-15, the archive's first season
RAW_SUBDIR = Path("cbbdata") / "torvik_archive"

# httpx logs request URLs at INFO, and ours carry the key as a query parameter.
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)


class CbbdataError(RuntimeError):
    """A fetch failed. The message never contains the key."""


def read_key(path: Path | None = None) -> str:
    p = path or config.CBBDATA_KEY_FILE
    try:
        key = p.read_text().strip()
    except OSError as e:
        raise CbbdataError(f"no cbbdata key at {p} ({type(e).__name__})") from None
    if not key:
        raise CbbdataError(f"cbbdata key file {p} is empty")
    return key


def season_of(day: date) -> int:
    """Season end year: games from July on belong to next year's season (2026-11 -> 2027)."""
    return day.year + 1 if day.month >= 7 else day.year


def archive_path(year: int, raw_dir: Path | None = None) -> Path:
    return (raw_dir or config.RAW_DIR) / RAW_SUBDIR / f"{year}.parquet"


def fetch_year(
    client: PoliteClient,
    key: str,
    year: int,
    *,
    refresh: bool = False,
    today: date | None = None,
    raw_dir: Path | None = None,
) -> tuple[Path, bool]:
    """Save one season's archive as <raw>/cbbdata/torvik_archive/<year>.parquet.

    Past seasons are cached forever; the current season is refetched on every call (its file
    grows daily). Returns (path, fetched_now)."""
    path = archive_path(year, raw_dir)
    current = season_of(today or date.today())
    # an empty past season (cbbdata hadn't loaded it) is retried rather than cached forever
    if path.exists() and not refresh and year < current and row_count(path) > 0:
        return path, False
    try:
        body = client.get_bytes(URL, {"year": year, "key": key})
    except FetchError as e:
        raise CbbdataError(str(e).replace(key, "***")) from None
    if body[:4] != b"PAR1":
        # error bodies are small JSON/text; show a short head, scrubbed of the key
        head = body[:200].decode("utf-8", "replace").replace(key, "***")
        raise CbbdataError(f"season {year}: not a Parquet file ({len(body)} bytes): {head!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(body)
    tmp.replace(path)
    return path, True


# ---------- pure ----------


def row_count(path: Path) -> int:
    con = duckdb.connect(":memory:")
    try:
        return con.execute("SELECT count(*) FROM read_parquet(?)", [str(path)]).fetchone()[0]
    finally:
        con.close()


# Output columns of parse_archive, in order.
COLUMNS = (
    "season",
    "as_of_date",
    "team",
    "conf",
    "rank",
    "barthag",
    "adj_o",
    "adj_d",
    "adj_tempo",
    "wab",
    "wins",
    "losses",
)


def _record(rec: Any) -> tuple[int | None, int | None]:
    if not isinstance(rec, str) or "-" not in rec:
        return None, None
    w, _, l_ = rec.partition("-")
    try:
        return int(w), int(l_)
    except ValueError:
        return None, None


def _num(v: Any) -> float | None:
    return None if v is None else float(v)


def parse_archive(path: Path) -> list[dict[str, Any]]:
    """Rows of one season's archive file: one dict per (team, as_of_date), keys = COLUMNS.

    Reads with an in-memory DuckDB (no warehouse). Duplicate (team, date) rows keep the first."""
    con = duckdb.connect(":memory:")
    try:
        cur = con.execute("SELECT * FROM read_parquet(?)", [str(path)])
        names = [d[0] for d in cur.description]
        raw = [dict(zip(names, r, strict=True)) for r in cur.fetchall()]
    finally:
        con.close()
    out: dict[tuple[str, date], dict[str, Any]] = {}
    for r in raw:
        team = (r.get("team") or "").strip()
        d = r.get("date")
        if not team or d is None:
            continue
        if not isinstance(d, date):
            d = date.fromisoformat(str(d)[:10])
        wins, losses = _record(r.get("record"))
        row = {
            "season": int(r["year"]),
            "as_of_date": d,
            "team": team,
            "conf": r.get("conf"),
            "rank": None if r.get("rank") is None else int(r["rank"]),
            "barthag": _num(r.get("barthag")),
            "adj_o": _num(r.get("adj_o")),
            "adj_d": _num(r.get("adj_d")),
            "adj_tempo": _num(r.get("adj_tempo")),
            "wab": _num(r.get("wab")),
            "wins": wins,
            "losses": losses,
        }
        out.setdefault((team, d), row)
    return sorted(out.values(), key=lambda x: (x["as_of_date"], x["team"]))


# ---------- team map: Barttorvik name -> ESPN team_id ----------

# Reviewed by hand 2026-11-19: names whose normalized form matches no ESPN location/short name.
# Renamed or merged programs map to the ESPN id of today's program. None = not in our ESPN data.
MANUAL_MATCHES: dict[str, str | None] = {
    "Albany": "399",  # UAlbany
    "Appalachian St.": "2026",  # App State
    "Arkansas Little Rock": "2031",  # Little Rock
    "Arkansas Pine Bluff": "2029",
    "Bethune Cookman": "2065",
    "Cal Baptist": "2856",  # California Baptist
    "College of Charleston": "232",  # Charleston
    "Connecticut": "41",  # UConn
    "Detroit": "2174",  # Detroit Mercy
    "Dixie St.": "3101",  # renamed Utah Tech (2022)
    "Fort Wayne": "2870",  # Purdue Fort Wayne
    "IPFW": "2870",  # Purdue Fort Wayne
    "Gardner Webb": "2241",
    "Grambling St.": "2755",  # Grambling
    "Houston Baptist": "2277",  # renamed Houston Christian (2022)
    "IUPUI": "85",  # renamed IU Indianapolis (2024)
    "Illinois Chicago": "82",  # UIC
    "LIU": "112358",  # Long Island University
    "LIU Brooklyn": "112358",  # merged into LIU (2019)
    "Louisiana Lafayette": "309",  # Louisiana
    "Louisiana Monroe": "2433",  # UL Monroe
    "McNeese St.": "2377",  # McNeese
    "Miami FL": "2390",  # Miami
    "Mississippi": "145",  # Ole Miss
    "Nebraska Omaha": "2437",  # Omaha
    "New Orleans": "2443",  # ESPN: LSU New Orleans
    "Nicholls St.": "2447",  # Nicholls
    "North Carolina St.": "152",  # NC State
    "Sam Houston St.": "2534",  # Sam Houston
    "San Jose St.": "23",  # San José State
    "Savannah St.": None,  # left D1 after 2018-19; not in our ESPN data (cache starts 2021-22)
    "Seattle": "2547",  # Seattle U
    "Southeastern Louisiana": "2545",  # SE Louisiana
    "St. Francis NY": "2597",  # St. Francis Brooklyn (left D1 2023)
    "St. Francis PA": "2598",  # Saint Francis
    "Tennessee Martin": "2630",  # UT Martin
    "Texas A&M Commerce": "2837",  # renamed East Texas A&M (2024)
    "Texas A&M Corpus Chris": "357",  # Texas A&M-Corpus Christi
    "UMKC": "140",  # Kansas City
    "USC Upstate": "2908",  # South Carolina Upstate
}

MAP_COLUMNS = ("torvik_team", "espn_team_id", "espn_name", "match", "first_season", "last_season")


def normalize_name(name: str | None) -> str:
    """Lowercase, '&' -> 'and', 'St.' -> 'state', punctuation dropped: 'Alabama St.' and
    'Alabama State' compare equal."""
    s = (name or "").lower().replace("&", "and")
    s = re.sub(r"\bst\.(?=\s|$)", "state", s)
    s = re.sub(r"[^a-z0-9 ]", "", s)
    return re.sub(" +", " ", s).strip()


def match_teams(
    torvik_seasons: dict[str, set[int]],
    espn_teams: dict[str, dict[str, Any]],
    manual: dict[str, str | None] = MANUAL_MATCHES,
) -> list[dict[str, Any]]:
    """One map row per Barttorvik name. `espn_teams` is {team_id: {location, shortDisplayName,
    displayName}}. Order: manual entry, then a unique match on normalized location or short
    name; anything else is left unmatched (match = "none") for review."""
    index: dict[str, set[str]] = {}
    for tid, t in espn_teams.items():
        for field in ("location", "shortDisplayName"):
            key = normalize_name(t.get(field))
            if key:
                index.setdefault(key, set()).add(tid)
    rows = []
    for name in sorted(torvik_seasons):
        seasons = torvik_seasons[name]
        if name in manual:
            tid, how = manual[name], "manual"
        else:
            cands = index.get(normalize_name(name), set())
            tid, how = (next(iter(cands)), "auto") if len(cands) == 1 else (None, "none")
        rows.append(
            {
                "torvik_team": name,
                "espn_team_id": tid,
                "espn_name": espn_teams.get(tid, {}).get("displayName") if tid else None,
                "match": how if tid else "none",
                "first_season": min(seasons),
                "last_season": max(seasons),
            }
        )
    return rows


def map_collisions(rows: list[dict[str, Any]]) -> list[tuple[str, list[str]]]:
    """ESPN ids that two Barttorvik names share in an overlapping season range (a renamed
    program keeps one id across non-overlapping ranges, which is fine)."""
    by_id: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if r["espn_team_id"]:
            by_id.setdefault(r["espn_team_id"], []).append(r)
    out = []
    for tid, rs in by_id.items():
        for i, a in enumerate(rs):
            for b in rs[i + 1 :]:
                if a["first_season"] <= b["last_season"] and b["first_season"] <= a["last_season"]:
                    out.append((tid, [a["torvik_team"], b["torvik_team"]]))
    return out
