class BettingConfig:
    # Bankroll
    STARTING_BANKROLL = 100  # Starting bankroll in dollars
    MAX_BET_SIZE_PCT = 0.1    # Maximum 2% of bankroll per bet
    KELLY_FRACTION = 0.25      # Use 25% Kelly for conservative sizing
    
    # Edge
    MIN_EDGE = 0.03           # Minimum 3% edge to place bet (model_prob - market_prob)
    MIN_CONFIDENCE = 0.60     # Minimum 60% win probability to consider betting
    
    # Risk Limits
    MAX_BETS_PER_DAY = 5      # Maximum number of bets per day
    DAILY_LOSS_LIMIT_PCT = 0.25  # Stop betting if down 5% in a day
    MAX_DRAWDOWN_PCT = 0.20   # Alert if drawdown exceeds 20%
    
    # Model Settings
    MODEL_PATH = './models/basketball_model.json'
    CONFIDENCE_THRESHOLD_HIGH = 0.70  # High confidence threshold
    CONFIDENCE_THRESHOLD_LOW = 0.30   # Low confidence threshold
    
    # Odds Settings
    # Books to track (for future Phase 3 implementation)
    SHARP_BOOKS = ['BetOnline', 'Pinnacle', 'LowVig']
    SOFT_BOOKS = ['DraftKings', 'FanDuel', 'BetMGM', 'Caesars']
    
    # Logging
    LOG_DIR = './logs/betting'
    PREDICTIONS_LOG = 'predictions.csv'
    BETS_LOG = 'bets.csv'
    PERFORMANCE_LOG = 'performance.csv'
    
    # Alerts
    ALERT_ON_HIGH_EDGE = 0.10  # Alert if edge exceeds 10% (potential data issue)
    ALERT_ON_LOSS_STREAK = 5   # Alert after 5 consecutive losses
    
    @classmethod
    def getMaxBetAmount(cls, current_bankroll):
        return current_bankroll * cls.MAX_BET_SIZE_PCT
    
    @classmethod
    def getDailyLossLimit(cls, current_bankroll):
        return current_bankroll * cls.DAILY_LOSS_LIMIT_PCT
    
    @classmethod
    def validateBet(cls, bet_size, current_bankroll, daily_losses, bets_today):
        max_bet = cls.getMaxBetAmount(current_bankroll)
        daily_limit = cls.getDailyLossLimit(current_bankroll)
        
        if bet_size > max_bet:
            return False, f"Bet size ${bet_size:.2f} exceeds max ${max_bet:.2f}"
        
        if daily_losses >= daily_limit:
            return False, f"Daily loss limit ${daily_limit:.2f} reached"
        
        if bets_today >= cls.MAX_BETS_PER_DAY:
            return False, f"Max bets per day ({cls.MAX_BETS_PER_DAY}) reached"
        
        return True, "Valid"
