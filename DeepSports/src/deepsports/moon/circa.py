"""Reprice To The Moon proposals at Circa's lines (read-only, watch-only).

Another job writes Circa's lines, read off the owner's screenshots, to
`<config.CIRCA_LINES_DIR>/<YYYY-MM-DD>.json` (`$DEEPSPORTS_CIRCA_LINES`, else
`$DEEPSPORTS_CIRCA_DIR/lines`, else /Volumes/ExFATStorag/DeepSports/circa/lines):

    {"date": "2026-11-14", "read_at": ISO8601, "files": [...],
     "lines": [{"game_id": "401..." | null, "league": ..., "away": "..", "home": "..",
                "market": "spread" | "total" | "moneyline", "side": "home" | "away" | "over" |
                "under", "line": -1.5 | null, "price": -110, "rotation": "823" | null}]}

`line` is from the bet side's view, like the model-picks runs. This module reads that JSON
directly (it does not import `deepsports.circa`). For each proposed leg (`reprice`):
- same line: Circa's price is used if it is at least the slate's price, else the leg is dropped
- another line: the leg is kept (at Circa's line and price) only if Circa is at least as good on
  BOTH the line and the price (+8.5 -110 vs +8 -110); otherwise it is dropped with the reason
  (e.g. line better, price worse), for the owner to judge by hand
- no Circa entry: the leg stays, marked "not on Circa screenshots: check by hand"
Teams (when a line has no game_id) match only on whole normalized names: "Kansas" never matches
"Arkansas", nor "Texas" "Texas Tech".
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

from deepsports import config
from deepsports.moon import sim

ENV_LINES = "DEEPSPORTS_CIRCA_LINES"
ENV_DIR = "DEEPSPORTS_CIRCA_DIR"
DEFAULT_DIR = config.CIRCA_LINES_DIR
UNCHECKED = "not on Circa screenshots: check by hand"


def lines_dir() -> Path:
    """`config.CIRCA_LINES_DIR`, with its env vars re-read at call time (same precedence)."""
    if os.environ.get(ENV_LINES):
        return Path(os.environ[ENV_LINES])
    if os.environ.get(ENV_DIR):
        return Path(os.environ[ENV_DIR]) / "lines"
    return config.CIRCA_LINES_DIR


def default_path(day: date) -> Path:
    return lines_dir() / f"{day.isoformat()}.json"


def load(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """(payload, None) or (None, why it can't be used)."""
    try:
        data = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return None, f"no Circa lines file ({path})"
    except (OSError, ValueError) as e:
        return None, f"Circa lines file unreadable ({path}: {type(e).__name__})"
    if not isinstance(data, dict) or not isinstance(data.get("lines"), list):
        return None, f"Circa lines file has no 'lines' list ({path})"
    return data, None


def _norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _team_match(circa_name: Any, names: Sequence[str]) -> bool:
    """Whole normalized names only (case, spaces and punctuation ignored): no substrings."""
    c = _norm(circa_name)
    return bool(c) and any(c == _norm(n) for n in names if _norm(n))


def find(leg, lines: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """Circa's entry for the leg's game, market and side: by game_id, else by league + teams."""
    same = [q for q in lines if q.get("market") == leg.market and q.get("side") == leg.side]
    for q in same:
        if q.get("game_id") and str(q["game_id"]) == str(leg.game_id):
            return q
    for q in same:
        if q.get("game_id"):
            continue
        if q.get("league") and leg.league and _norm(q["league"]) != _norm(leg.league):
            continue
        if _team_match(q.get("away"), leg.away_names) and _team_match(
            q.get("home"), leg.home_names
        ):
            return q
    return None


def line_cmp(market: str, side: str, mine: float | None, circa: float | None) -> int:
    """+1 if Circa's line is better for the bettor, 0 if the same, -1 if worse."""
    if market == "moneyline" or mine is None or circa is None:
        return 0
    d = float(circa) - float(mine)
    if abs(d) < 1e-9:
        return 0
    if market == "total" and side == "over":
        d = -d  # a lower total is better for an over
    return 1 if d > 0 else -1


def _fmt_line(market: str, line: float) -> str:
    return f"{line:+g}" if market == "spread" else f"{line:g}"


def _relabel(leg, new_line: float) -> str:
    old = _fmt_line(leg.market, leg.line)
    new = _fmt_line(leg.market, new_line)
    return leg.label.replace(old, new) if old in leg.label else f"{leg.label} ({new} at Circa)"


def _quote(market: str, line: float | None, price: int) -> str:
    return f"{price:+d}" if market == "moneyline" or line is None else (
        f"{_fmt_line(market, line)} {price:+d}"
    )  # fmt: skip


def _why(lg, c_line: float | None, price: int, ref: int, cmp: int, price_ok: bool) -> str:
    """E.g. 'Circa +8.5 -130 vs +8 -110: line better, price worse; check by hand'."""
    vs = f"Circa {_quote(lg.market, c_line, price)} vs {_quote(lg.market, lg.line, ref)}"
    if cmp == 0:
        return f"{vs}: price worse"
    line = "line better" if cmp > 0 else "line worse"
    pr = "price worse" if not price_ok else "price better" if price != ref else "same price"
    return f"{vs}: {line}, {pr}" + ("; check by hand" if (cmp > 0) != price_ok else "")


def reprice(legs: Sequence, payload: Mapping[str, Any]) -> tuple[list, list[str]]:
    """(legs kept, notes). Kept legs carry `source` 'circa' or 'unchecked'."""
    lines = [q for q in payload.get("lines", []) if isinstance(q, Mapping)]
    kept, notes = [], []
    for lg in legs:
        q = find(lg, lines)
        if q is None or q.get("price") is None:
            kept.append(replace(lg, source="unchecked"))
            continue
        try:
            price = int(q["price"])
            sim.decimal(price)
        except (TypeError, ValueError):
            kept.append(replace(lg, source="unchecked"))
            continue
        c_line = None if q.get("line") is None else float(q["line"])
        if lg.market != "moneyline" and c_line is None:
            kept.append(replace(lg, source="unchecked"))
            continue
        cmp = line_cmp(lg.market, lg.side, lg.line, c_line)
        ref = lg.ref_price or lg.price
        price_ok = sim.decimal(price) >= sim.decimal(ref) - 1e-9
        rot = f" (#{q['rotation']})" if q.get("rotation") else ""
        if cmp == 0 and price_ok:
            kept.append(replace(lg, price=price, label=lg.label + rot, source="circa"))
        elif cmp > 0 and price_ok:
            kept.append(replace(lg, line=c_line, price=price, label=_relabel(lg, c_line) + rot,
                                source="circa"))  # fmt: skip
        else:
            notes.append(f"Dropped {lg.label}: {_why(lg, c_line, price, ref, cmp, price_ok)}")
    return kept, notes
