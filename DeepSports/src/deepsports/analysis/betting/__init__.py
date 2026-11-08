"""Betting-grade library: grade spread/total/moneyline bets with refunded pushes (-110 by
default), ROI with a day-clustered bootstrap CI, CLV, price sensitivity, drawdown, and the
3x line-move audit. Ported from the DeepSeek edge study (collab/deepseek/lab/harness.py,
audit.py, context.py); docs/DECISIONS.md has the history.

- `grading`: pure grading and summary statistics (`grade`, `summarize`, ...).
- `audit`: pure line-move audit (`audit`, `flag_moves`, `move_medians`).
- `loaders`: read-only warehouse loaders shaped for the two above.
"""

from deepsports.analysis.betting.audit import AuditResult, audit, flag_moves, move_medians
from deepsports.analysis.betting.grading import (
    DEFAULT_PRICE,
    GradeResult,
    bootstrap_ci,
    bootstrap_rois,
    clv,
    drawdown,
    grade,
    grade_bet,
    normalize_bet,
    outcome,
    price_sensitivity,
    profit_on_win,
    summarize,
)
from deepsports.analysis.betting.loaders import (
    load_games,
    load_lines,
    load_odds,
    load_odds_raw,
    read_raw_summary,
)

__all__ = [
    "DEFAULT_PRICE",
    "AuditResult",
    "GradeResult",
    "audit",
    "bootstrap_ci",
    "bootstrap_rois",
    "clv",
    "drawdown",
    "flag_moves",
    "grade",
    "grade_bet",
    "load_games",
    "load_lines",
    "load_odds",
    "load_odds_raw",
    "move_medians",
    "normalize_bet",
    "outcome",
    "price_sensitivity",
    "profit_on_win",
    "read_raw_summary",
    "summarize",
]
