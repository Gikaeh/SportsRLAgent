"""The Odds API live capture files -> line rows (pure apart from reading the file).

Files come from `deepsports odds-api-history live` under RAW_DIR/oddsapi/live/<sport>/:
- `<UTC slot>.json.gz` (scheduled capture, from 2026-11-23): an envelope
  {"timestamp": fetch time, "sport", "markets", "scope", "credits_*", "data": [event, ...]}.
- older key checks under `<sport>/<markets>/<scope>/<UTC stamp>.json.gz`: the bare event list;
  the snapshot time is the file name's stamp.

One row per event x book x market x outcome, with `side` normalised for joining:
totals -> "over"/"under", spreads/h2h -> "home"/"away" (by team name), else None.
Matching rows to ESPN game ids is not done here: the et-v2 line matcher
(`analysis/et_v2_lines.py`, PR #45) was not on main when this was written.
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deepsports.sources.oddsapi_history import parse_snapshot

LINE_COLUMNS = (
    "snapshot_ts",
    "event_id",
    "sport_key",
    "commence_time",
    "home_team",
    "away_team",
    "book",
    "market",
    "side",
    "outcome",
    "point",
    "price",
    "last_update",
)


def stamp_ts(name: str) -> datetime | None:
    """'20261123T200000Z.json.gz' -> 2026-11-23 20:00 UTC; None for other names."""
    try:
        return datetime.strptime(name.split(".")[0], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def side_of(
    market: str | None, outcome: str | None, home: str | None, away: str | None
) -> str | None:
    name = (outcome or "").strip()
    if market == "totals":
        return name.lower() if name.lower() in ("over", "under") else None
    if name and name == home:
        return "home"
    if name and name == away:
        return "away"
    return None


def live_rows(resp: Any, snapshot_ts: datetime | None = None) -> list[dict[str, Any]]:
    """An envelope or a bare live list -> rows with LINE_COLUMNS. The envelope's "timestamp"
    wins over `snapshot_ts`."""
    out = []
    for r in parse_snapshot(resp, snapshot_ts):
        out.append(
            {
                "snapshot_ts": r["snapshot_ts"],
                "event_id": r["event_id"],
                "sport_key": r["sport_key"],
                "commence_time": r["commence_time"],
                "home_team": r["home_team"],
                "away_team": r["away_team"],
                "book": r["book"],
                "market": r["market"],
                "side": side_of(r["market"], r["outcome"], r["home_team"], r["away_team"]),
                "outcome": r["outcome"],
                "point": r["point"],
                "price": r["price"],
                "last_update": r["market_last_update"],
            }
        )
    return out


def read_live_file(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        resp = json.load(fh)
    return live_rows(resp, stamp_ts(Path(path).name))
