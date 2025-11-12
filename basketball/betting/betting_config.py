class BettingConfig:
    # Bankroll
    STARTING_BANKROLL = 100  # Starting bankroll in dollars
    MAX_BET_SIZE_PCT = 0.1    # Maximum 2% of bankroll per bet
    KELLY_FRACTION = 0.25      # Use 25% Kelly for conservative sizing
    MAX_RISK_PCT = 0.80
    
    # Edge
    MIN_EDGE = 0.03           # Minimum 3% edge to place bet (model_prob - market_prob)
    MIN_PROBABILITY = 0.55     # Minimum 60% win probability to consider betting
    
    # Risk Limits
    MAX_BETS_PER_DAY = 5      # Maximum number of bets per day
    DAILY_LOSS_LIMIT_PCT = 0.25  # Stop betting if down 5% in a day
    MAX_DRAWDOWN_PCT = 0.20   # Alert if drawdown exceeds 20%
    
    # Model Settings
    MODEL_PATH = './models/basketball_h2h_model.json'
    CONFIDENCE_THRESHOLD_HIGH = 0.70  # High confidence threshold
    CONFIDENCE_THRESHOLD_LOW = 0.30   # Low confidence threshold
    
    # Odds Settings
    # Books to track (for future Phase 3 implementation)
    SHARP_BOOKS = ['BetOnline', 'Pinnacle', 'LowVig']
    SOFT_BOOKS = ['DraftKings', 'FanDuel', 'BetMGM', 'Caesars']
    NEVADA_BOOKS = ['betmgm', 'caesars']
    
    # Logging
    LOG_DIR = '././logs/betting'
    H2H_BETS_LOG = 'h2h_bets.csv'
    SPREAD_BETS_LOG = 'spread_bets.csv'
    TOTAL_BETS_LOG = 'total_bets.csv'
    
    # Alerts
    ALERT_ON_HIGH_EDGE = 0.10  # Alert if edge exceeds 10% (potential data issue)
    ALERT_ON_LOSS_STREAK = 5   # Alert after 5 consecutive losses
