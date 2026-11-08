"""Read-only analysis of the DeepSports warehouse: home court, market accuracy, Elo, and
prediction model v1 (features.py, model.py, backtest.py).

Every function takes an open DuckDB connection and never writes to it. See analysis/README.md
for what each metric means.
"""

from deepsports.analysis.backtest import evaluate_backtest, run_backtest, walk_forward
from deepsports.analysis.elo import EloResult, elo_ratings, win_probability
from deepsports.analysis.evaluate import evaluate_elo
from deepsports.analysis.features import FEATURES, build_features
from deepsports.analysis.market import home_court, market_accuracy
from deepsports.analysis.metrics import (
    american_to_decimal,
    brier,
    devig_probability,
    log_loss,
)
from deepsports.analysis.model import ModelV1, predict_upcoming
from deepsports.analysis.record import prediction_card, prediction_record, pretip_predictions

__all__ = [
    "FEATURES",
    "EloResult",
    "ModelV1",
    "build_features",
    "evaluate_backtest",
    "predict_upcoming",
    "prediction_card",
    "prediction_record",
    "pretip_predictions",
    "run_backtest",
    "walk_forward",
    "american_to_decimal",
    "brier",
    "devig_probability",
    "elo_ratings",
    "evaluate_elo",
    "home_court",
    "log_loss",
    "market_accuracy",
    "win_probability",
]
