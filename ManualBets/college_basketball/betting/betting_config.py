class BettingConfig:
    # Same edge rules as basketball/betting/betting_config.py (docs/DECISIONS.md).
    MIN_EDGE_H2H = 0.02
    MIN_EDGE_SPREAD = 3
    MIN_EDGE_TOTAL = 8
    MIN_PROBABILITY = 0.55

    # Used only when the training metadata has no measured residual std.
    SPREAD_RESIDUAL_SIGMA_FALLBACK = 11.5
    TOTAL_RESIDUAL_SIGMA_FALLBACK = 16.5

    # Bets are withheld until both teams have this many games (docs/DECISIONS.md).
    # In the holdout, spread gaps with under 3 games played lost more as they grew.
    MIN_GAMES_PLAYED = 5

    # Same priority weights as the NBA recommender.
    PRIORITY_WEIGHTS = {'h2h': 0.3, 'spread': 1.0, 'total': 0.001}

    BOOKS = ['betmgm', 'caesars']

    # Same sizing as the NBA recommender.
    STARTING_BANKROLL = 50
    KELLY_FRACTION = 0.20
    MAX_BET_SIZE_PCT = 0.05
    MAX_RISK_PCT = 0.5
    MIN_BET_AMOUNT = 1
