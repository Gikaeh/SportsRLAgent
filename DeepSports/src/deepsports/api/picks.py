"""GET /api/picks/today: the latest models-only picks run (watch-only), for the apps' Picks button.

Files only (the run dirs under reports/model-picks/), never DuckDB, so it works while a job holds
the warehouse. Never returns stakes: picks carry a 1-unit `stake` field internally, which is
dropped here. Contract: docs/API.md, "Picks".
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

MAX_AGE = timedelta(hours=36)  # longest gap between runs is 30 h (Sunday 08:00 -> Monday 14:00)
MORE_MAX = 10
PICK_FIELDS = ("game_id", "league", "label", "market", "side", "line", "price", "tier",
               "ds_edge", "mb_edge", "early")  # fmt: skip


def _team(t: Mapping[str, Any] | None) -> dict:
    t = t or {}
    return {"abbr": t.get("abbr"), "name": t.get("name")}


def _pick(p: Mapping[str, Any], games: Mapping[str, Mapping[str, Any]]) -> dict:
    g = games.get(str(p["game_id"])) or {}
    out = {k: p.get(k) for k in PICK_FIELDS}
    out["away"], out["home"] = _team(g.get("away")), _team(g.get("home"))
    out["tip_utc"] = g.get("tip_utc")
    books = {}
    for book, q in (p.get("books") or {}).items():
        if isinstance(q, Mapping) and q.get("price") is not None:
            books[book] = {"line": q.get("line"), "price": q["price"]}
    out["books"] = books
    best = p.get("best")
    out["best"] = (
        {"line": best.get("point"), "price": best.get("price"), "book": best.get("book")}
        if isinstance(best, Mapping)
        else None
    )
    return out


def latest_run(root: Path, now: datetime | None = None) -> dict[str, Any]:
    """The newest run no older than MAX_AGE, shaped for the apps; `available: false` if none."""
    now = now or datetime.now(UTC)
    best: tuple[datetime, Path, dict] | None = None
    for f in root.glob("*/picks.json"):
        try:
            r = json.loads(f.read_text())
            created = datetime.fromisoformat(r["created_at"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if timedelta(0) <= now - created <= MAX_AGE and (best is None or created > best[0]):
            best = (created, f, r)
    if best is None:
        return {"available": False, "run_at": None, "top": [], "more": [],
                "counts": {"strong": 0, "lean": 0}}  # fmt: skip
    created, f, r = best
    try:
        slate = json.loads((f.parent / "slate.json").read_text())
    except (OSError, ValueError):
        slate = {}
    games = {str(g["game_id"]): g for g in slate.get("games", []) if "game_id" in g}
    top = [_pick(p, games) for p in r.get("top", [])]
    in_top = {(p["game_id"], p["market"]) for p in top}
    rest = [p for p in r.get("picks", []) if (p["game_id"], p["market"]) not in in_top]
    picks = r.get("picks", [])
    return {
        "available": True,
        "run_at": created.astimezone(UTC).isoformat(),
        "rule_version": r.get("rule_version"),
        "top": top,
        "more": [_pick(p, games) for p in rest[:MORE_MAX]],
        "counts": {
            "strong": sum(1 for p in picks if p.get("tier") == "strong"),
            "lean": sum(1 for p in picks if p.get("tier") == "lean"),
        },
    }
