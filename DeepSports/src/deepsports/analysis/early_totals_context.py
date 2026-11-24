"""Market context of each night-before et-v1 / et-v1-alt bet (pure; owner-approved 2026-11-23).

Describe-only: nothing here changes, filters or ranks a bet. For every logged bet one row records
the market around the bet line's time (the WH screenshot `read_at`, else the Caesars feed
`grabbed_at`):
- the ESPN opener (`odds_snapshots` source 'opening') and, as its stand-in, the first ESPN
  scoreboard (DraftKings) pregame capture at or before the bet time: this warehouse fetches the
  opening row only after the game is final, so a row written the night before has no opener
  (the 2026-11-22 line-move study: the opener equals the first DraftKings capture in 91% of games);
- the ESPN scoreboard pregame total nearest at or before the bet time (`dk_*`);
- the Caesars 21:00 feed total, the WH screenshot total and the Circa night-before screenshot
  total for the bet's side, when present;
- derived, in points, signed toward the pick (s = +1 over, -1 under):
  `momentum` = s * (DK at bet time - opener)           > 0: the market moved the pick's way;
  `wh_better_than_dk` = s * (DK at bet time - bet line) > 0: the bet line beat DraftKings;
  `circa_better_than_wh` = s * (bet line - Circa)       > 0: Circa's number was better.
  Raw differences too: `wh_minus_dk` = line - DK, `circa_minus_wh` = Circa - line.

Rows go to `<REPORTS_DIR>/early-totals/context.jsonl`, keyed by (rule_version, game_id); the first
row per bet is frozen. I/O lives in `early_totals_cli.py` (`early-totals context`).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from deepsports.analysis import early_totals as et

CONTEXT_VERSION = 1


def _dt(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else None


def _iso(v: datetime | None) -> str | None:
    return None if v is None else v.isoformat(timespec="seconds")


def bet_time(bet: Mapping[str, Any]) -> tuple[datetime | None, str | None]:
    """(when the bet line was seen, which field): the WH screenshot `read_at` for a screenshot
    line, else the Caesars feed `grabbed_at`, else the bet's `logged_at`."""
    order = ["book_grabbed_at", "logged_at"]
    if bet.get("line_source") == "screenshot":
        order.insert(0, "book_read_at")
    for key in order:
        t = _dt(bet.get(key))
        if t is not None:
            return t, key
    return None, None


def _sign(side: str) -> int:
    return 1 if side == "over" else -1


def _r(v: float | None) -> float | None:
    return None if v is None else round(v, 2) + 0.0  # + 0.0: no -0.0 in the file


def market_at(
    snaps: Sequence[Mapping[str, Any]], at: datetime | None, league: str = et.LEAGUE
) -> dict[str, Any]:
    """From one game's `odds_snapshots` rows ({source, provider, captured_at, over_under}): the
    opener (latest 'opening' row; its captured_at is the tip, not a posting time), the first and
    the latest 'pregame' rows captured at or before `at`. Insane totals are ignored."""
    ok = [s for s in snaps if et._sane_total(s.get("over_under"), league) is not None]
    opening = [s for s in ok if s.get("source") == "opening"]
    op = max(opening, key=lambda s: _dt(s["captured_at"]), default=None)
    pre = []
    if at is not None:
        pre = sorted(
            (s for s in ok if s.get("source") == "pregame" and _dt(s["captured_at"]) is not None),
            key=lambda s: _dt(s["captured_at"]),
        )
        pre = [s for s in pre if _dt(s["captured_at"]) <= at]
    first, last = (pre[0], pre[-1]) if pre else (None, None)
    return {
        "opener_total": None if op is None else float(op["over_under"]),
        "opener_provider": None if op is None else op.get("provider"),
        "first_pregame_total": None if first is None else float(first["over_under"]),
        "first_pregame_at": None if first is None else _iso(_dt(first["captured_at"])),
        "dk_total": None if last is None else float(last["over_under"]),
        "dk_provider": None if last is None else last.get("provider"),
        "dk_captured_at": None if last is None else _iso(_dt(last["captured_at"])),
        "dk_age_min": None
        if last is None
        else round((at - _dt(last["captured_at"])).total_seconds() / 60, 1),
    }


def _quote(totals: Mapping[str, Mapping[str, Mapping]], gid: str, side: str) -> dict | None:
    return ((totals or {}).get(gid) or {}).get(side)


def derive(
    side: str,
    line: float,
    dk: float | None,
    opener: float | None,
    first_pregame: float | None,
    circa: float | None,
) -> dict[str, Any]:
    """The signed differences (see the module docstring). The momentum base is the ESPN opener,
    else the first pregame capture (`momentum_from` says which)."""
    s = _sign(side)
    base, base_from = (
        (opener, "opening")
        if opener is not None
        else (first_pregame, "first_pregame")
        if first_pregame is not None
        else (None, None)
    )
    have_m = dk is not None and base is not None
    return {
        "momentum": _r(s * (dk - base)) if have_m else None,
        "momentum_from": base_from if have_m else None,
        "wh_minus_dk": None if dk is None else _r(line - dk),
        "wh_better_than_dk": None if dk is None else _r(s * (dk - line)),
        "circa_minus_wh": None if circa is None else _r(circa - line),
        "circa_better_than_wh": None if circa is None else _r(s * (line - circa)),
    }


def context_row(
    bet: Mapping[str, Any],
    snaps: Sequence[Mapping[str, Any]],
    wh_shots: Mapping[str, Any] | None,
    feed: Mapping[str, Any] | None,
    circa: Mapping[str, Any] | None,
    written_at: datetime,
    backfilled: bool = False,
) -> dict[str, Any]:
    """One context row for a logged bet. `snaps`: that game's opening + pregame snapshot rows;
    `wh_shots`, `feed`, `circa`: the game day's night-before lines payloads (Circa lines contract)
    or None. Pure."""
    gid, side, line = str(bet["game_id"]), bet["side"], float(bet["line"])
    at, at_from = bet_time(bet)
    m = market_at(snaps, at, bet.get("league", et.LEAGUE))
    fq = _quote(et.book_totals(feed), gid, side)
    wq = _quote(et.book_totals(wh_shots), gid, side)
    cq = _quote(et.book_totals(circa), gid, side)
    circa_total = None if cq is None else cq["line"]
    return {
        "context_version": CONTEXT_VERSION,
        "rule_version": bet["rule_version"],
        "game_id": gid,
        "game_date": bet.get("game_date"),
        "side": side,
        "line": line,
        "line_source": bet.get("line_source"),
        "written_at": _iso(written_at),
        "backfilled": bool(backfilled),
        "bet_time": _iso(at),
        "bet_time_from": at_from,
        **m,
        "feed_total": None if fq is None else fq["line"],
        "feed_price": None if fq is None else fq["price"],
        "feed_grabbed_at": (feed or {}).get("grabbed_at") if fq else None,
        "wh_shot_total": None if wq is None else wq["line"],
        "wh_shot_price": None if wq is None else wq["price"],
        "wh_read_at": (wh_shots or {}).get("read_at") if wq else None,
        "circa_total": circa_total,
        "circa_price": None if cq is None else cq["price"],
        "circa_read_at": (circa or {}).get("read_at") if cq else None,
        **derive(
            side, line, m["dk_total"], m["opener_total"], m["first_pregame_total"], circa_total
        ),  # fmt: skip
    }


def missing(
    bets: Iterable[Mapping[str, Any]], existing: Iterable[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    """Bets with no context row yet (key: rule version + game), first one per key."""
    seen = {(r.get("rule_version"), str(r.get("game_id"))) for r in existing}
    out = []
    for b in bets:
        k = (b.get("rule_version"), str(b.get("game_id")))
        if k not in seen:
            seen.add(k)
            out.append(b)
    return out


# ---------- describe-only view ----------


def momentum_now(row: Mapping[str, Any], opener: float | None) -> float | None:
    """The row's momentum re-based on the ESPN opener when the warehouse has it now (a fixed
    pre-bet number, fetched after the game); else the stored value."""
    if opener is not None and row.get("dk_total") is not None:
        return _r(_sign(row["side"]) * (row["dk_total"] - opener))
    return row.get("momentum")


def _momentum_group(v: float | None) -> str:
    return "?" if v is None else ">=0 (toward pick)" if v >= 0 else "<0 (against pick)"


def _circa_group(v: float | None) -> str:
    if v is None:
        return "no Circa"
    return "Circa better" if v > 0 else "same" if v == 0 else "WH better"


def summarize(
    graded: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]],
    openers: Mapping[str, float] | None = None,
    rule_version: str | None = None,
) -> dict[str, Any]:
    """Win % / CLV of graded bets (`early_totals.grade_bet` rows, one rule version) split by
    momentum >= 0 vs < 0 and by Circa better than WH. Describe-only: not a pre-registered test."""
    ctx = {(r["rule_version"], str(r["game_id"])): r for r in reversed(rows)}  # first row wins
    openers = openers or {}
    joined = []
    for g in graded:
        c = ctx.get((g["rule_version"], str(g["game_id"])))
        joined.append((g, c))
    done = [(g, c) for g, c in joined if g["grade"] != "pending"]
    with_ctx = [c for _, c in joined if c is not None]
    out: dict[str, Any] = {
        "rule_version": rule_version or (graded[0]["rule_version"] if graded else None),
        "bets": len(graded),
        "graded": len(done),
        "with_context": len(with_ctx),
        "backfilled": sum(bool(c.get("backfilled")) for c in with_ctx),
        "coverage": {
            "dk_at_bet_time": sum(c.get("dk_total") is not None for c in with_ctx),
            "opener_espn": sum(
                (openers.get(str(c["game_id"])) or c.get("opener_total")) is not None
                for c in with_ctx
            ),
            "momentum": sum(
                momentum_now(c, openers.get(str(c["game_id"]))) is not None for c in with_ctx
            ),
            "feed": sum(c.get("feed_total") is not None for c in with_ctx),
            "wh_screenshot": sum(c.get("wh_shot_total") is not None for c in with_ctx),
            "circa": sum(c.get("circa_total") is not None for c in with_ctx),
        },
        "splits": {},
    }
    keys = {
        "momentum": lambda c: _momentum_group(
            None if c is None else momentum_now(c, openers.get(str(c["game_id"])))
        ),
        "circa_vs_wh": lambda c: _circa_group(None if c is None else c.get("circa_better_than_wh")),
    }
    for name, key in keys.items():
        groups: dict[str, list] = defaultdict(list)
        for g, c in done:
            groups[key(c)].append(g)
        out["splits"][name] = {k: et._record(v) for k, v in sorted(groups.items())}
    return out


def render(s: Mapping[str, Any]) -> str:
    def pct(v):
        return "-" if v is None else f"{v:.1%}"

    def rec(name, r):
        clv = "-" if r.get("clv_mean") is None else f"{r['clv_mean']:+.2f}"
        return (f"  {name}: {r['bets']} ({r['record']}), win {pct(r['win_pct'])},"
                f" CLV {clv} (n {r['clv_n']}), {r['units_profit']:+.2f}u")  # fmt: skip

    c = s["coverage"]
    lines = [
        f"Early totals {s['rule_version']} market context (describe-only, not a test):"
        f" {s['bets']} bets, {s['graded']} graded, context on {s['with_context']}"
        f" ({s['backfilled']} backfilled)",
        f"Coverage: DK at bet time {c['dk_at_bet_time']}, ESPN opener {c['opener_espn']},"
        f" momentum {c['momentum']}, Caesars feed {c['feed']}, WH screenshot"
        f" {c['wh_screenshot']}, Circa {c['circa']}",
        "Momentum (DK at bet time vs opener, toward the pick):",
        *(rec(k, r) for k, r in s["splits"]["momentum"].items()),
        "Circa vs WH (night-before, for the pick):",
        *(rec(k, r) for k, r in s["splits"]["circa_vs_wh"].items()),
    ]
    return "\n".join(lines)
