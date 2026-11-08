"""Scoring rules and odds conversions. Pure functions, stdlib only."""

import math
from collections.abc import Sequence

EPS = 1e-15


def american_to_decimal(ml: float | None) -> float | None:
    """American moneyline -> decimal odds (total payout per 1 staked).
    +150 -> 2.5, -130 -> 1.769..., 100 (EVEN) -> 2.0. Invalid values -> None."""
    if ml is None or -100 < ml < 100:
        return None
    return 1 + ml / 100 if ml > 0 else 1 + 100 / -ml


def devig_probability(home_ml: float | None, away_ml: float | None) -> float | None:
    """Market-implied home win probability with the bookmaker's margin (vig) removed:
    p_home = (1/d_home) / (1/d_home + 1/d_away)."""
    dh, da = american_to_decimal(home_ml), american_to_decimal(away_ml)
    if dh is None or da is None:
        return None
    ih, ia = 1 / dh, 1 / da
    return ih / (ih + ia)


def brier(probs: Sequence[float], outcomes: Sequence[int]) -> float | None:
    """Mean squared error of probabilities vs 0/1 outcomes. 0 is perfect, 0.25 is a coin flip."""
    if not probs:
        return None
    return sum((p - y) ** 2 for p, y in zip(probs, outcomes, strict=True)) / len(probs)


def log_loss(probs: Sequence[float], outcomes: Sequence[int]) -> float | None:
    """Mean negative log likelihood. 0 is perfect, ln 2 = 0.693 is a coin flip."""
    if not probs:
        return None
    total = 0.0
    for p, y in zip(probs, outcomes, strict=True):
        p = min(max(p, EPS), 1 - EPS)
        total -= math.log(p) if y else math.log(1 - p)
    return total / len(probs)
