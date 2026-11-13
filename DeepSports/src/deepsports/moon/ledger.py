"""To The Moon (betting) ledger: the owner's REAL bets, logged by hand after placing them.

An APPEND-ONLY CSV at `config.MOON_LEDGER_PATH` (`logs/moon/bets.csv`, edge 5). Nothing here
places or sends a wager, and the read API never serves this file (stakes stay on the Mac).

Row kinds (the `amount` column is the cash change of the moon account):
- deposit: money in (amount = +X)
- bet:     a placed bet (amount = -stake); market spread/total/moneyline/parlay. Parlay legs are a
           JSON list in `legs` (different games only: no same-game parlays)
- result:  a settled bet, `ref` = the bet id; result win/loss/push/void, amount = +payout
- void:    cancels the row `ref` (a mis-logged deposit, bet, result or adjust); amount = minus
           that row's amount. A voided result re-opens its bet
- adjust:  a correction of the balance with a required note (e.g. a book credit)
- note:    free text
Rows are never edited or deleted: corrections are new rows. The only write path is `_append`,
which opens the file in append mode and refuses an unexpected header, a duplicate id or a
file that doesn't end with a newline.

Lines are stored from the bet side's view (spread `home -1.5` = home gives 1.5), like the
model-picks runs. Grading reads finals from the warehouse (read-only) and appends `result` rows.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deepsports import config
from deepsports.analysis.betting.grading import outcome
from deepsports.moon.sim import decimal

COLUMNS = [
    "id", "created_at", "kind", "ref", "month", "tier", "book", "league", "game_id", "bet",
    "market", "side", "line", "price", "legs", "stake", "result", "payout", "amount", "note",
]  # fmt: skip
KINDS = ("deposit", "bet", "result", "void", "adjust", "note")
MARKETS = ("spread", "total", "moneyline", "parlay")
SIDES = {"spread": ("home", "away"), "total": ("over", "under"), "moneyline": ("home", "away")}
RESULTS = ("win", "loss", "push", "void")
DEFAULT_BOOK = "Circa"
PUSH_LEG_PRICE = -110  # a pushed parlay leg's price when the ledger has none for it


class LedgerError(ValueError):
    """Refused ledger operation (bad input or unexpected file layout)."""


def _path(path: Path | None) -> Path:
    return Path(path or config.MOON_LEDGER_PATH)


def read_rows(path: Path | None = None) -> list[dict[str, str]]:
    p = _path(path)
    if not p.exists() or p.stat().st_size == 0:
        return []
    with p.open(newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            raise LedgerError(f"{p}: header {reader.fieldnames} != expected {COLUMNS}")
        return list(reader)


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".") if v != int(v) else str(int(v))
    return str(v)


def _append(new: Sequence[Mapping[str, Any]], path: Path | None = None) -> list[dict[str, str]]:
    """Append rows (the ONLY write path). Never rewrites existing bytes."""
    p = _path(path)
    existing = read_rows(p)
    ids = {r["id"] for r in existing}
    if p.exists() and p.stat().st_size > 0:
        with p.open("rb") as f:
            f.seek(-1, 2)
            if f.read(1) != b"\n":
                raise LedgerError(f"{p} does not end with a newline; fix by hand before appending")
    out = []
    for r in new:
        unknown = set(r) - set(COLUMNS)
        if unknown:
            raise LedgerError(f"unknown columns {sorted(unknown)}")
        if r["kind"] not in KINDS:
            raise LedgerError(f"unknown kind {r['kind']!r}")
        if r["id"] in ids:
            raise LedgerError(f"duplicate id {r['id']}")
        ids.add(r["id"])
        out.append({c: _fmt(r.get(c)) for c in COLUMNS})
    p.parent.mkdir(parents=True, exist_ok=True)
    write_header = not p.exists() or p.stat().st_size == 0
    with p.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        if write_header:
            w.writeheader()
        w.writerows(out)
    return out


def init(path: Path | None = None) -> Path:
    """Create the ledger with just its header if missing (never touches an existing one)."""
    p = _path(path)
    if not p.exists() or p.stat().st_size == 0:
        _append([], p)
    else:
        read_rows(p)  # validates the header
    return p


def _next_id(rows: Sequence[Mapping[str, str]], extra: int = 0) -> str:
    n = max((int(r["id"]) for r in rows if r["id"].isdigit()), default=0)
    return str(n + 1 + extra)


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now(UTC)).astimezone(UTC)


def _month(now: datetime) -> str:
    return now.astimezone(config.LOCAL_TZ).strftime("%Y-%m")


def _base(rows, kind: str, now: datetime | None, month: str | None, note: str | None) -> dict:
    t = _now(now)
    return {
        "id": _next_id(rows),
        "created_at": t.isoformat(timespec="seconds"),
        "kind": kind,
        "month": month or _month(t),
        "note": note,
    }


# ---------- writers ----------


def add_deposit(
    amount: float,
    *,
    path: Path | None = None,
    now: datetime | None = None,
    month: str | None = None,
    note: str | None = None,
) -> dict[str, str]:
    if amount <= 0:
        raise LedgerError("a deposit must be positive (use void or adjust to correct)")
    rows = read_rows(path)
    return _append([_base(rows, "deposit", now, month, note) | {"amount": amount}], path)[0]


def _check_leg(leg: Mapping[str, Any]) -> dict[str, Any]:
    market, side = leg.get("market"), leg.get("side")
    if market not in SIDES:
        raise LedgerError(f"leg market must be one of {sorted(SIDES)}, got {market!r}")
    if side not in SIDES[market]:
        raise LedgerError(f"{market} side must be one of {SIDES[market]}, got {side!r}")
    if not leg.get("game_id"):
        raise LedgerError("every bet needs a game_id (ESPN id, as in the slate)")
    line = leg.get("line")
    if market != "moneyline" and line in (None, ""):
        raise LedgerError(f"a {market} bet needs a line")
    price = leg.get("price")
    if price not in (None, ""):
        decimal(float(price))
    return {
        "game_id": str(leg["game_id"]),
        "league": leg.get("league") or "",
        "market": market,
        "side": side,
        "line": None if market == "moneyline" or line in (None, "") else float(line),
        "price": None if price in (None, "") else int(price),
        "label": leg.get("label") or "",
    }


def add_bet(
    *,
    stake: float,
    price: int,
    market: str,
    game_id: str | None = None,
    league: str | None = None,
    side: str | None = None,
    line: float | None = None,
    legs: Sequence[Mapping[str, Any]] | None = None,
    bet: str | None = None,
    tier: str | None = None,
    book: str = DEFAULT_BOOK,
    path: Path | None = None,
    now: datetime | None = None,
    month: str | None = None,
    note: str | None = None,
) -> dict[str, str]:
    """Log a placed bet at the price actually taken. Parlays: market='parlay' and `legs`."""
    if stake <= 0:
        raise LedgerError("stake must be positive")
    decimal(price)
    if market not in MARKETS:
        raise LedgerError(f"market must be one of {MARKETS}, got {market!r}")
    row: dict[str, Any] = {"tier": tier, "book": book, "market": market, "price": int(price)}
    if market == "parlay":
        checked = [_check_leg(lg) for lg in legs or []]
        if len(checked) < 2:
            raise LedgerError("a parlay needs at least 2 legs")
        games = [lg["game_id"] for lg in checked]
        if len(set(games)) != len(games):
            raise LedgerError("same-game parlays are out of scope: every leg must be another game")
        row |= {
            "legs": json.dumps(checked, separators=(",", ":")),
            "league": "/".join(sorted({lg["league"] for lg in checked if lg["league"]})),
            "bet": bet or " + ".join(lg["label"] or _leg_text(lg) for lg in checked),
        }
    else:
        if legs:
            raise LedgerError("legs are only for parlays")
        lg = _check_leg(
            {"game_id": game_id, "league": league, "market": market, "side": side, "line": line,
             "price": price, "label": bet}
        )  # fmt: skip
        row |= {
            "league": lg["league"],
            "game_id": lg["game_id"],
            "side": lg["side"],
            "line": lg["line"],
            "bet": bet or _leg_text(lg),
        }
    rows = read_rows(path)
    base = _base(rows, "bet", now, month, note)
    return _append([base | row | {"stake": stake, "amount": -stake}], path)[0]


def _leg_text(lg: Mapping[str, Any]) -> str:
    if lg["market"] == "moneyline":
        return f"{lg['side']} ML"
    if lg["market"] == "spread":
        return f"{lg['side']} {lg['line']:+g}"
    return f"{lg['side']} {lg['line']:g}"


def _by_id(rows) -> dict[str, dict[str, str]]:
    return {r["id"]: r for r in rows}


def voided_ids(rows: Sequence[Mapping[str, str]]) -> set[str]:
    """Ids cancelled by a void row (a void itself cannot be voided)."""
    return {r["ref"] for r in rows if r["kind"] == "void"}


def live_rows(rows: Sequence[Mapping[str, str]]) -> list[Mapping[str, str]]:
    gone = voided_ids(rows)
    return [r for r in rows if r["id"] not in gone and r["kind"] != "void"]


def results_by_bet(rows: Sequence[Mapping[str, str]]) -> dict[str, Mapping[str, str]]:
    return {r["ref"]: r for r in live_rows(rows) if r["kind"] == "result"}


def open_bets(rows: Sequence[Mapping[str, str]]) -> list[Mapping[str, str]]:
    settled = results_by_bet(rows)
    return [r for r in live_rows(rows) if r["kind"] == "bet" and r["id"] not in settled]


def payout_for(bet: Mapping[str, str], result: str, legs_results: Sequence[str] = ()) -> float:
    """Total returned (stake included) for a settled bet at the price actually taken. A parlay
    with pushed legs pays the taken price scaled down by each pushed leg's decimal odds."""
    stake = float(bet["stake"])
    if result == "loss":
        return 0.0
    if result in ("push", "void"):
        return stake
    dec = decimal(float(bet["price"]))
    if bet["market"] == "parlay" and legs_results:
        for lg, res in zip(json.loads(bet["legs"]), legs_results, strict=True):
            if res == "push":
                dec /= decimal(lg["price"] if lg.get("price") is not None else PUSH_LEG_PRICE)
    return round(stake * dec, 2)


def add_result(
    ref: str,
    result: str,
    *,
    payout: float | None = None,
    legs_results: Sequence[str] = (),
    path: Path | None = None,
    now: datetime | None = None,
    note: str | None = None,
) -> dict[str, str]:
    """Settle bet `ref` (graded or by hand). Refuses a bet that is voided or already settled."""
    if result not in RESULTS:
        raise LedgerError(f"result must be one of {RESULTS}")
    rows = read_rows(path)
    bet = _by_id(rows).get(ref)
    if bet is None or bet["kind"] != "bet":
        raise LedgerError(f"no bet with id {ref}")
    if ref in voided_ids(rows):
        raise LedgerError(f"bet {ref} is voided")
    if ref in results_by_bet(rows):
        raise LedgerError(f"bet {ref} is already settled (void that result row first)")
    pay = payout_for(bet, result, legs_results) if payout is None else float(payout)
    base = _base(rows, "result", now, bet["month"], note)
    row = base | {
        "ref": ref,
        "tier": bet["tier"],
        "book": bet["book"],
        "league": bet["league"],
        "game_id": bet["game_id"],
        "bet": bet["bet"],
        "market": bet["market"],
        "price": bet["price"],
        "stake": bet["stake"],
        "result": result,
        "payout": pay,
        "amount": pay,
    }
    return _append([row], path)[0]


def add_void(
    ref: str, note: str, *, path: Path | None = None, now: datetime | None = None
) -> dict[str, str]:
    """Cancel row `ref` with a new row (its amount reversed). A bet with a live result must have
    that result voided first."""
    if not note:
        raise LedgerError("a void needs a note saying why")
    rows = read_rows(path)
    target = _by_id(rows).get(ref)
    if target is None:
        raise LedgerError(f"no row with id {ref}")
    if target["kind"] in ("void", "note"):
        raise LedgerError(f"row {ref} is a {target['kind']} and cannot be voided")
    if ref in voided_ids(rows):
        raise LedgerError(f"row {ref} is already voided")
    if target["kind"] == "bet" and ref in results_by_bet(rows):
        raise LedgerError(f"bet {ref} has a result; void the result row first")
    amount = -float(target["amount"] or 0)
    base = _base(rows, "void", now, target["month"], note)
    return _append([base | {"ref": ref, "bet": target["bet"], "amount": amount}], path)[0]


def add_adjust(
    amount: float, note: str, *, path: Path | None = None, now: datetime | None = None
) -> dict[str, str]:
    if not note:
        raise LedgerError("an adjust needs a note saying why")
    rows = read_rows(path)
    return _append([_base(rows, "adjust", now, None, note) | {"amount": amount}], path)[0]


def add_note(note: str, *, path: Path | None = None, now: datetime | None = None) -> dict:
    rows = read_rows(path)
    return _append([_base(rows, "note", now, None, note)], path)[0]


# ---------- summary ----------


def summary(rows: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    """Balance, deposits, staked, profit vs keeping the cash, record, per month."""
    live = live_rows(rows)
    amt = lambda r: float(r["amount"] or 0)  # noqa: E731
    deposits = sum(amt(r) for r in live if r["kind"] == "deposit")
    balance = sum(amt(r) for r in live if r["kind"] in ("deposit", "bet", "result", "adjust"))
    res = results_by_bet(rows)
    bets = [r for r in live if r["kind"] == "bet"]
    settled = [b for b in bets if b["id"] in res]
    counts = {k: sum(res[b["id"]]["result"] == k for b in settled) for k in RESULTS}
    staked = sum(float(b["stake"]) for b in settled)
    profit = sum(float(res[b["id"]]["payout"]) - float(b["stake"]) for b in settled)
    months: dict[str, dict[str, float]] = {}
    for r in live:
        m = months.setdefault(r["month"], {"deposits": 0.0, "bets": 0, "staked": 0.0, "net": 0.0})
        if r["kind"] == "deposit":
            m["deposits"] += amt(r)
        elif r["kind"] == "bet":
            m["bets"] += 1
            m["staked"] += float(r["stake"])
        if r["kind"] in ("bet", "result", "adjust"):
            m["net"] += amt(r)
    first = min((r["month"] for r in live if r["kind"] == "deposit"), default=None)
    return {
        "deposits": round(deposits, 2),
        "balance": round(balance, 2),
        "vs_cash": round(balance - deposits, 2),
        "open": open_bets(rows),
        "open_stake": round(sum(float(b["stake"]) for b in open_bets(rows)), 2),
        "settled": len(settled),
        "record": f"{counts['win']}-{counts['loss']}-{counts['push'] + counts['void']}",
        "staked": round(staked, 2),
        "profit": round(profit, 2),
        "roi": None if not staked else round(profit / staked, 4),
        "first_month": first,
        "months": months,
    }


def plan_month(first_month: str | None, now: datetime | None = None) -> int:
    """1-based month of the 12-month plan, counted from the first deposit's month."""
    if not first_month:
        return 1
    y0, m0 = map(int, first_month.split("-"))
    cur = _month(_now(now))
    y1, m1 = map(int, cur.split("-"))
    return (y1 - y0) * 12 + (m1 - m0) + 1


# ---------- grading (reads finals, appends result rows) ----------


def _home_line(leg: Mapping[str, Any]) -> float | None:
    line = leg.get("line")
    if line in (None, ""):
        return None
    line = float(line)
    if leg["market"] == "spread":
        return line if leg["side"] == "home" else -line
    return line


def grade_leg(leg: Mapping[str, Any], final: Mapping[str, Any]) -> str:
    margin = final["home_score"] - final["away_score"]
    total = final["home_score"] + final["away_score"]
    return outcome(leg["market"], leg["side"], _home_line(leg), margin, total)


def bet_legs(bet: Mapping[str, str]) -> list[dict[str, Any]]:
    if bet["market"] == "parlay":
        return json.loads(bet["legs"])
    return [{"game_id": bet["game_id"], "market": bet["market"], "side": bet["side"],
             "line": bet["line"]}]  # fmt: skip


def settle(bet: Mapping[str, str], finals: Mapping[str, Mapping[str, Any]]):
    """(result, legs_results) when every leg's game is final, else None (pure)."""
    legs = bet_legs(bet)
    if any(lg["game_id"] not in finals for lg in legs):
        return None
    res = [grade_leg(lg, finals[lg["game_id"]]) for lg in legs]
    if "loss" in res:
        return "loss", res
    if all(r == "push" for r in res):
        return "push", res
    return "win", res


def grade(
    finals: Mapping[str, Mapping[str, Any]],
    *,
    path: Path | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Append a result row for every open bet whose games are all final. `finals` maps
    game_id -> {home_score, away_score} (e.g. `ensemble_bets.load_finals` on a read-only
    connection). Returns the rows appended (or that would be, with dry_run)."""
    out = []
    for bet in open_bets(read_rows(path)):
        s = settle(bet, finals)
        if s is None:
            continue
        result, legs_res = s
        if dry_run:
            out.append({"ref": bet["id"], "bet": bet["bet"], "result": result,
                        "payout": payout_for(bet, result, legs_res)})  # fmt: skip
            continue
        out.append(
            add_result(
                bet["id"],
                result,
                legs_results=legs_res if bet["market"] == "parlay" else (),
                path=path,
                now=now,
                note="graded from warehouse finals",
            )
        )
    return out


def game_ids(rows: Sequence[Mapping[str, str]]) -> list[str]:
    """Game ids of the open bets (for loading finals)."""
    return sorted({lg["game_id"] for b in open_bets(rows) for lg in bet_legs(b)})
