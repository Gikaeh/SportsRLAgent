"""`et-v1-alt`: watch-only shadow of the et-v1 night-before college totals rule (pure logic).

Pre-registration: docs/results/2026-11-22-altitude-feature.md (owner-approved 2026-11-22). The rule
is et-v1's exactly (`early_totals.find_bets`: same games, MB export, WH lines, prices, timing), with
the `ncaab-v1.1alt` total (ncaab-v1 + venue altitude in the total model) in place of `ncaab-v1`'s.
Where et-v1 uses `ncaab-v1-early` (a team under 5 games) the shadow uses it too, and where the alt
row is missing or older than the v1 row (its predict step failed) it falls back to the v1 number,
so those games can never make the two rules differ. Logged in the same 21:00 run to its own file;
et-v1's files and output are never touched.

Metrics (graded with `early-totals grade --alt`):
- primary: on paired nights (nights the shadow ran), units of et-v1-alt minus et-v1, counting only
  the games where the two rules differ (a bet in one log only, or opposite sides);
- secondary: mean (actual - model total) at venues >= 1,200 m, ncaab-v1.1alt vs ncaab-v1 (target:
  closer to 0), and total MAE on every graded game with both versions (alt must not be worse by
  more than 0.02).
Verdict after the 2026-27 regular season (Selection Sunday 2027-03-14), no early stop. Pass =
differing bets net >= 0 units, smaller altitude bias, MAE within 0.02; a pass makes et-v1-alt a
candidate for et-v2, considered only after et-v1's own 300-bet verdict.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any

from deepsports.analysis import early_totals as et

ALT_RULE_VERSION = "et-v1-alt"
ALT_DS_VERSION = "ncaab-v1.1alt"
BASE_DS_VERSION = "ncaab-v1"
HIGH_VENUE_M = 1200
MAE_TOLERANCE = 0.02
SEASON_YEAR = 2027  # 2026-27
VERDICT_AFTER = date(2027, 3, 14)  # Selection Sunday 2027: the regular season is over
# The alt row is written right after ncaab-v1 by the same sync; an alt row older than this
# before the v1 row is a stale one from an earlier run (today's alt step failed).
MAX_ALT_LAG = timedelta(hours=1)


def alt_ds_preds(
    base: Mapping[str, Mapping[str, Any]], alt: Mapping[str, Mapping[str, Any]]
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    """(DS predictions for et-v1-alt, counts). `base` = et-v1's per-game DS prediction
    (`ensemble_bets.load_predictions`), `alt` = the latest ncaab-v1.1alt row per game. Only games
    where et-v1 uses ncaab-v1 get the alt number; the rest keep et-v1's."""
    out: dict[str, dict[str, Any]] = {}
    counts = {"alt": 0, "fallback_v1": 0, "other": 0}
    for gid, p in base.items():
        a = alt.get(gid)
        if p.get("model_version") != BASE_DS_VERSION:
            counts["other"] += 1
            out[gid] = dict(p)
        elif a is None or a.get("pred_total") is None or _stale(a, p):
            counts["fallback_v1"] += 1
            out[gid] = dict(p)
        else:
            counts["alt"] += 1
            out[gid] = dict(a) | {"model_version": ALT_DS_VERSION}
    return out, counts


def _stale(alt: Mapping[str, Any], base: Mapping[str, Any]) -> bool:
    a, b = alt.get("created_at"), base.get("created_at")
    if not isinstance(a, datetime) or not isinstance(b, datetime):
        return False
    return a < b - MAX_ALT_LAG


def find_alt_bets(
    games: Sequence[Mapping[str, Any]],
    base_preds: Mapping[str, Mapping[str, Any]],
    alt_preds: Mapping[str, Mapping[str, Any]],
    mb_export: Mapping[str, Any] | None,
    early: Mapping[str, Any] | None,
    now: datetime,
    game_date: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """et-v1's `find_bets` on the alt DS numbers; rows carry rule_version et-v1-alt."""
    preds, used = alt_ds_preds(base_preds, alt_preds)
    bets, counts = et.find_bets(games, preds, mb_export, early, now, game_date)
    bets = [b | {"rule_version": ALT_RULE_VERSION} for b in bets]
    return bets, counts | {f"ds_{k}": v for k, v in used.items()}


def differences(
    v1_bets: Sequence[Mapping[str, Any]], alt_bets: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Games where the two logs differ: {game_id, kind (alt_only|v1_only|flip), v1, alt}."""
    v1 = {str(b["game_id"]): b for b in v1_bets}
    alt = {str(b["game_id"]): b for b in alt_bets}
    out = []
    for gid in sorted(v1.keys() | alt.keys()):
        a, b = alt.get(gid), v1.get(gid)
        if a and b and a["side"] == b["side"]:
            continue
        kind = "alt_only" if b is None else "v1_only" if a is None else "flip"
        out.append({"game_id": gid, "kind": kind, "v1": b, "alt": a})
    return out


def paired_units(
    v1_graded: Sequence[Mapping[str, Any]],
    alt_graded: Sequence[Mapping[str, Any]],
    paired_dates: set[str],
    through: date | None = None,
) -> dict[str, Any]:
    """Primary metric: units of et-v1-alt minus et-v1 on the differing games of paired nights
    (graded `early_totals.grade_bet` rows; a differing game with a pending side is left out)."""

    def keep(rows):
        return [
            r
            for r in rows
            if r["game_date"] in paired_dates
            and (through is None or r["game_date"] <= through.isoformat())
        ]

    v1, alt = keep(v1_graded), keep(alt_graded)
    diffs, pending = [], 0
    for d in differences(v1, alt):
        sides = [x for x in (d["v1"], d["alt"]) if x is not None]
        if any(x["grade"] == "pending" for x in sides):
            pending += 1
            continue
        pa = d["alt"]["profit"] if d["alt"] else 0.0
        pv = d["v1"]["profit"] if d["v1"] else 0.0
        diffs.append(d | {"day": sides[0]["game_date"], "diff": round(pa - pv, 4)})
    by_kind = {}
    for kind in ("alt_only", "v1_only", "flip"):
        rows = [d for d in diffs if d["kind"] == kind]
        side = "v1" if kind == "v1_only" else "alt"
        by_kind[kind] = et._record([d[side] for d in rows]) if rows else {"bets": 0}
    units = round(sum(d["diff"] for d in diffs), 2)
    return {
        "paired_nights": len({r["game_date"] for r in v1 + alt} & paired_dates),
        "v1_bets": len(v1),
        "alt_bets": len(alt),
        "differing": len(diffs),
        "differing_pending": pending,
        "diff_units": units,
        "diff_units_ci": et.day_ci([(d["day"], d["diff"]) for d in diffs], stat=sum)
        if diffs
        else None,
        "by_kind": by_kind,
    }


def model_compare(rows: Sequence[Mapping[str, Any]], through: date | None = None) -> dict[str, Any]:
    """Secondary metrics from graded games with both versions: rows {day, elevation_m, actual,
    v1, alt} (totals). Bias = mean(actual - model); MAE diff = alt - v1 (negative = alt better),
    95% CI resampling whole days."""
    rows = [r for r in rows if through is None or r["day"] <= through.isoformat()]

    def mean(xs):
        return None if not xs else round(sum(xs) / len(xs), 3)

    high = [
        r for r in rows if r.get("elevation_m") is not None and r["elevation_m"] >= HIGH_VENUE_M
    ]
    diffs = [(r["day"], abs(r["alt"] - r["actual"]) - abs(r["v1"] - r["actual"])) for r in rows]
    return {
        "games": len(rows),
        "mae_v1": mean([abs(r["v1"] - r["actual"]) for r in rows]),
        "mae_alt": mean([abs(r["alt"] - r["actual"]) for r in rows]),
        "mae_diff": mean([d for _, d in diffs]),
        "mae_diff_ci": et.day_ci(diffs) if diffs else None,
        "high_venue_games": len(high),
        "high_bias_v1": mean([r["actual"] - r["v1"] for r in high]),
        "high_bias_alt": mean([r["actual"] - r["alt"] for r in high]),
    }


def verdict(paired: Mapping[str, Any], models: Mapping[str, Any] | None, today: date) -> str:
    """Pre-registered decision; nothing before the end of the 2026-27 regular season."""
    if today <= VERDICT_AFTER:
        return f"collecting (verdict after {VERDICT_AFTER.isoformat()}, no early stop)"
    if not models or models.get("mae_diff") is None or models.get("high_bias_alt") is None:
        return "no verdict: model comparison unavailable"
    bias_ok = abs(models["high_bias_alt"]) < abs(models["high_bias_v1"])
    if paired["diff_units"] >= 0 and bias_ok and models["mae_diff"] <= MAE_TOLERANCE:
        return "PASS (candidate for et-v2, after et-v1's 300-bet verdict)"
    return "FAIL"


def summarize(
    v1_graded: Sequence[Mapping[str, Any]],
    alt_graded: Sequence[Mapping[str, Any]],
    paired_dates: set[str],
    models_rows: Sequence[Mapping[str, Any]] | None,
    today: date,
) -> dict[str, Any]:
    """The full alt report: its own record, the paired difference, the model comparison and the
    verdict (computed on games through VERDICT_AFTER once that date has passed)."""
    through = VERDICT_AFTER if today > VERDICT_AFTER else None
    paired = paired_units(v1_graded, alt_graded, paired_dates, through)
    models = None if models_rows is None else model_compare(models_rows, through)
    own = et.summarize([r for r in alt_graded if r["game_date"] in paired_dates])
    own["rule_version"] = ALT_RULE_VERSION
    own.pop("verdict", None)  # et-v1's 300-bet verdict doesn't apply to the shadow
    return {
        "rule_version": ALT_RULE_VERSION,
        "ds_version": ALT_DS_VERSION,
        "record": own,
        "paired": paired,
        "models": models,
        "verdict": verdict(paired, models, today),
    }


def render(s: Mapping[str, Any]) -> str:
    def num(v, fmt="+.2f"):
        return "-" if v is None else format(v, fmt)

    p, m, r = s["paired"], s.get("models"), s["record"]
    ci = p.get("diff_units_ci")
    k = p["by_kind"]
    lines = [
        f"Early totals {s['rule_version']} (shadow of et-v1, watch-only): {s['verdict']}",
        f"{p['paired_nights']} paired nights; alt {r['bets']} graded ({r['record']}),"
        f" {r['units_profit']:+.2f}u; et-v1 {p['v1_bets']} bets on the same nights",
        f"Differing bets {p['differing']} ({p['differing_pending']} pending): alt - et-v1"
        f" {p['diff_units']:+.2f}u"
        + (f" [{ci[0]:+.2f}, {ci[1]:+.2f}]" if ci else "")
        + f"; alt-only {k['alt_only'].get('record', '0-0-0')},"
        f" v1-only {k['v1_only'].get('record', '0-0-0')}, flips {k['flip']['bets']}",
    ]
    if m:
        mci = m.get("mae_diff_ci")
        lines.append(
            f"Totals, {m['games']} graded games: MAE v1 {num(m['mae_v1'], '.2f')}"
            f" alt {num(m['mae_alt'], '.2f')} (diff {num(m['mae_diff'], '+.3f')}"
            + (f" [{mci[0]:+.3f}, {mci[1]:+.3f}]" if mci else "")
            + f", must be <= +{MAE_TOLERANCE}); >= {HIGH_VENUE_M} m ({m['high_venue_games']}):"
            f" bias v1 {num(m['high_bias_v1'])} alt {num(m['high_bias_alt'])}"
        )
    else:
        lines.append("Totals comparison unavailable (no venues table or no graded games)")
    return "\n".join(lines)
