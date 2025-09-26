# MLB Betting Project: Complete Implementation Roadmap
**ML Baseline → RL Injury-Adaptive Betting System**

## 🎯 Project Overview

**Goal**: Build a betting system that uses ML for base predictions and RL to dynamically adjust confidence based on real-time player availability/injuries.

**Why This Works**: 
- ML handles static game prediction (pitcher quality, team strength, weather)
- RL handles dynamic adaptation (injuries, lineup changes, player impact learning)
- Creates a system that can adapt in real-time without full model retraining

---

## 📊 Phase 1: Data Foundation (Weeks 1-3)

### 1.1 Core Data Collection
**Priority Order:**

1. **Betting Data** (Essential)
   - Single sportsbook for ML baseline (recommend Pinnacle - most accurate)
   - Multiple books for RL phase (DraftKings, FanDuel, BetMGM, Pinnacle)
   - Focus on **moneyline odds** (home/away win probabilities)
   - Data structure:
   ```python
   columns = ['game_id', 'date', 'home_team', 'away_team', 
              'pinnacle_opening_home_ml', 'pinnacle_closing_home_ml',
              'home_score', 'away_score', 'home_won']
   ```

2. **Team/Player Stats** (Core Features)
   - Recent team performance (last 10 games)
   - Starting pitcher stats (ERA, WHIP, K/9, recent form)
   - Team offensive stats (runs per game, OPS, vs lefty/righty)
   - Rest days, travel schedule
   - Source: Baseball-Reference, FanGraphs

3. **Park Factors** (Contextual)
   - Use Baseball Savant scraper (already built)
   - Stadium-specific run environment adjustments
   - Weather impact on scoring

4. **Injury/Player Availability** (RL Component)
   - Daily injury reports (ESPN, MLB.com, CBS Sports)
   - Starting lineups (announced ~2 hours before games)
   - Player importance weights (to be learned by RL)

### 1.2 Data Pipeline Setup
```python
# Daily data collection routine
def daily_data_update():
    # 1. Scrape today's games and odds
    # 2. Update injury reports  
    # 3. Collect yesterday's results
    # 4. Update historical database
    # 5. Trigger model updates if needed
```

### 1.3 Data Quality Validation
- Missing data handling (games postponed, rain delays)
- Odds format standardization (American → implied probability)
- Player name disambiguation (Mike Trout vs M. Trout)
- Historical data backfill (2020-2024 minimum)

---

## 🤖 Phase 2: ML Baseline Model (Weeks 4-6)

### 2.1 Feature Engineering
**Static Game Features:**
```python
core_features = [
    # Pitching matchup
    'home_sp_era', 'away_sp_era', 'home_sp_whip', 'away_sp_whip',
    'home_sp_k9', 'away_sp_k9', 'home_sp_recent_form', 'away_sp_recent_form',
    
    # Team recent performance  
    'home_wins_l10', 'away_wins_l10', 'home_runs_l10', 'away_runs_l10',
    'home_era_l10', 'away_era_l10', 'home_vs_rhp', 'away_vs_lhp',
    
    # Game context
    'is_day_game', 'temperature', 'park_run_factor', 'rest_days_home', 'rest_days_away',
    
    # Market signals
    'home_implied_prob', 'line_movement', 'market_consensus'
]
```

### 2.2 Model Selection & Training
**Recommended Models (test multiple):**
1. **XGBoost** - Usually best for tabular data
2. **Random Forest** - Good interpretability  
3. **Logistic Regression** - Simple baseline
4. **Neural Network** - Deep learning baseline

**Training Strategy:**
- **Time series split** (train on 2020-2022, validate on 2023, test on 2024)
- **Walk-forward validation** (retrain monthly)
- **Cross-validation within time periods** (avoid look-ahead bias)

### 2.3 Model Evaluation
**Metrics:**
- **Accuracy** - Basic win rate
- **Log Loss** - Calibrated probability assessment  
- **ROC AUC** - Discrimination ability
- **Betting ROI** - Actual profitability simulation
- **Kelly Criterion** - Optimal bet sizing

**Baseline Targets:**
- >52.38% accuracy (break-even at -110 odds)
- >55% accuracy (sustainable profitability)
- Low log loss (well-calibrated probabilities)

### 2.4 Model Interpretation
- **Feature importance** - Which stats matter most?
- **SHAP values** - Individual prediction explanations
- **Confidence intervals** - Uncertainty quantification
- **Worst case analysis** - When does model fail?

---

## 🎮 Phase 3: RL Injury-Adaptive System (Weeks 7-10)

### 3.1 RL Problem Definition
**State Space:**
```python
state = [
    base_ml_confidence,           # From Phase 2 model
    home_key_player_statuses,     # 5 key players * 2 features each
    away_key_player_statuses,     # 5 key players * 2 features each  
    learned_player_weights,       # Historical impact scores
    recent_adjustment_accuracy,   # How well is RL performing?
    market_volatility,           # Odds movement magnitude
    days_since_last_update       # Temporal context
]
# Total: ~25-30 dimensional state space
```

**Action Space:**
```python
actions = [
    # Confidence adjustments from -1.0 to +1.0 in 0.1 increments
    -1.0, -0.9, -0.8, ..., 0.8, 0.9, 1.0  # 21 total actions
]
```

**Reward Function:**
```python
def calculate_reward(base_confidence, adjusted_confidence, actual_result):
    base_error = abs(base_confidence - actual_result)
    adjusted_error = abs(adjusted_confidence - actual_result) 
    
    # Reward improvement in prediction accuracy
    improvement = base_error - adjusted_error
    
    # Scale reward by magnitude of improvement
    if improvement > 0.1:
        return +2  # Significant improvement
    elif improvement > 0.05:
        return +1  # Moderate improvement  
    elif improvement > -0.05:
        return 0   # No change
    else:
        return -1  # Made prediction worse
```

### 3.2 RL Architecture
**Deep Q-Network (DQN):**
```python
class InjuryAdaptiveDQN(nn.Module):
    def __init__(self, state_dim=30, action_dim=21):
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(state_dim, 128),
            nn.ReLU(),
            nn.BatchNorm1d(128),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.BatchNorm1d(64), 
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, action_dim)
        )
    
    def forward(self, state):
        return self.network(state)
```

**Training Components:**
- **Experience Replay Buffer** (10,000 transitions)
- **Target Network** (updated every 1000 steps)
- **Epsilon-greedy exploration** (start 0.9, decay to 0.05)
- **Learning rate scheduling** (start 0.001, decay)

### 3.3 Player Impact Learning
**Dynamic Player Importance:**
```python
class PlayerImpactTracker:
    def __init__(self):
        self.player_weights = {}  # {player_name: importance_score}
        self.impact_history = {}  # {player_name: [impact_observations]}
    
    def update_impact(self, player_name, game_context, impact_observed):
        # Exponential moving average with context awareness
        current_weight = self.player_weights.get(player_name, 0.1)
        context_multiplier = self.get_context_multiplier(game_context)
        
        new_observation = impact_observed * context_multiplier
        updated_weight = 0.1 * new_observation + 0.9 * current_weight
        
        self.player_weights[player_name] = np.clip(updated_weight, 0.0, 1.0)
```

### 3.4 Real-Time Data Integration
**Injury Monitoring Pipeline:**
```python
def monitor_player_status():
    sources = [
        'https://www.mlb.com/news/topic/injury-report',
        'https://www.espn.com/mlb/injuries',
        'https://rotoworld.com/baseball/mlb/injury-report'
    ]
    
    # Scrape every 30 minutes during season
    # Parse injury severity: [Out, Doubtful, Questionable, Probable, Active]
    # Update player status database
    # Trigger RL confidence adjustments if needed
```

---

## 📈 Phase 4: Integration & Backtesting (Weeks 11-12)

### 4.1 System Integration
**Complete Pipeline:**
```python
def make_betting_decision(game_data, current_date):
    # 1. Get base ML prediction
    base_confidence = ml_model.predict_proba(game_data)[0][1]
    
    # 2. Get current player statuses
    player_statuses = injury_tracker.get_current_status(current_date)
    
    # 3. Build RL state
    rl_state = build_rl_state(base_confidence, game_data, player_statuses)
    
    # 4. Get RL confidence adjustment  
    adjustment = rl_agent.choose_action(rl_state)
    
    # 5. Calculate final confidence
    final_confidence = np.clip(base_confidence + adjustment, 0.01, 0.99)
    
    # 6. Make betting decision
    if final_confidence > betting_threshold:
        bet_size = kelly_criterion(final_confidence, odds)
        return {'bet': True, 'confidence': final_confidence, 'size': bet_size}
    else:
        return {'bet': False}
```

### 4.2 Backtesting Framework
**Historical Simulation:**
- **Walk-forward testing** (2020-2024 data)
- **Injury data replay** - Simulate real-time injury discovery
- **Multiple betting strategies** - Fixed size vs Kelly vs RL-optimized
- **Transaction costs** - Account for betting fees, line shopping time
- **Bankroll management** - Drawdown limits, position sizing

**Performance Metrics:**
```python
backtest_metrics = {
    'total_return': 0.0,
    'roi': 0.0,
    'sharpe_ratio': 0.0,
    'max_drawdown': 0.0,
    'win_rate': 0.0,
    'avg_bet_size': 0.0,
    'total_bets_placed': 0,
    'ml_only_performance': 0.0,  # Baseline comparison
    'rl_improvement': 0.0,       # Added value from RL
    'best_month': 0.0,
    'worst_month': 0.0
}
```

---

## 🚀 Phase 5: Production Deployment (Weeks 13-14)

### 5.1 Production Architecture
**System Components:**
```python
# Daily workflow
def production_pipeline():
    # 6:00 AM: Update injury reports
    # 8:00 AM: Collect overnight line movements  
    # 10:00 AM: Generate predictions for today's games
    # 2:00 PM: Final injury check & lineup confirmations
    # 3:00 PM: Place bets (games start ~7 PM)
    # 11:00 PM: Collect results & update models
```

**Infrastructure:**
- **Database** - PostgreSQL for game data, Redis for real-time odds
- **Monitoring** - Track model performance, data pipeline health
- **Alerts** - Email/SMS for significant injury news, model anomalies
- **Logging** - All predictions, bets, and outcomes for analysis

### 5.2 Risk Management
**Safeguards:**
- **Maximum bet size** - Never risk more than 2% of bankroll per game
- **Daily loss limits** - Stop betting if down >5% of bankroll in one day
- **Model confidence thresholds** - Only bet on games with >60% confidence
- **Injury impact limits** - Cap RL adjustments at ±0.3 confidence points
- **Manual override** - Human can disable system if needed

### 5.3 Continuous Improvement
**Model Updates:**
- **Weekly performance review** - Analyze wins/losses, model drift
- **Monthly model retraining** - Incorporate new data, feature engineering
- **Seasonal adjustments** - Different strategies for April vs September
- **A/B testing** - Compare model variations on subset of bets

---

## 📋 Implementation Checklist

### Phase 1: Data Foundation ✅
- [ ] Set up data collection pipeline
- [ ] Historical data backfill (2020-2024)
- [ ] Park factors scraper (completed)
- [ ] Injury monitoring system
- [ ] Data quality validation
- [ ] Database schema design

### Phase 2: ML Baseline ✅
- [ ] Feature engineering pipeline
- [ ] Model training framework
- [ ] Cross-validation setup
- [ ] Performance evaluation metrics
- [ ] Model interpretation tools
- [ ] Baseline profitability assessment

### Phase 3: RL System ✅
- [ ] RL environment design
- [ ] DQN architecture implementation
- [ ] Player impact tracking system
- [ ] Experience replay buffer
- [ ] Training loop & hyperparameter tuning
- [ ] RL model evaluation

### Phase 4: Integration ✅
- [ ] End-to-end pipeline
- [ ] Backtesting framework
- [ ] Performance comparison (ML vs ML+RL)
- [ ] Sensitivity analysis
- [ ] Risk assessment
- [ ] Documentation

### Phase 5: Production ✅
- [ ] Production deployment
- [ ] Monitoring & alerting
- [ ] Risk management controls
- [ ] Performance tracking
- [ ] Continuous improvement process

---

## 🎯 Success Criteria

### Technical Milestones
- **ML Baseline**: >55% accuracy on 2024 test data
- **RL Enhancement**: >2% improvement in ROI over ML baseline
- **System Reliability**: <1% downtime during betting hours
- **Data Quality**: <0.5% missing critical features

### Business Objectives
- **Profitability**: Positive ROI over 6-month live period
- **Risk Management**: Maximum 15% drawdown
- **Scalability**: Handle 15+ games per day during peak season
- **Adaptability**: Successfully adapt to mid-season injury situations

---

## 🔧 Technology Stack

### Core Technologies
- **Python 3.9+** - Main development language
- **PostgreSQL** - Primary database
- **Redis** - Real-time data caching
- **PyTorch** - RL model implementation
- **Scikit-learn** - ML baseline models
- **XGBoost** - Gradient boosting models
- **Pandas/NumPy** - Data manipulation
- **Docker** - Containerization
- **GitHub Actions** - CI/CD pipeline

### External APIs & Data Sources
- **The Odds API** - Real-time betting odds
- **Baseball-Reference** - Historical stats
- **Baseball Savant** - Advanced metrics
- **OpenWeatherMap** - Weather data
- **ESPN/MLB.com** - Injury reports

---

## 📊 Expected Outcomes

### Pessimistic Scenario
- ML Baseline: 53% accuracy, 2% annual ROI
- RL Enhancement: +0.5% ROI improvement
- Total System: 2.5% annual ROI

### Realistic Scenario  
- ML Baseline: 55% accuracy, 5% annual ROI
- RL Enhancement: +2% ROI improvement  
- Total System: 7% annual ROI

### Optimistic Scenario
- ML Baseline: 57% accuracy, 8% annual ROI
- RL Enhancement: +4% ROI improvement
- Total System: 12% annual ROI

---

## 🚨 Risk Factors & Mitigation

### Technical Risks
- **Data source reliability** → Multiple backup sources
- **Model overfitting** → Rigorous cross-validation
- **RL instability** → Conservative exploration, experience replay

### Market Risks  
- **Odds movement** → Real-time monitoring, quick execution
- **Market efficiency improvement** → Continuous model updates
- **Betting limits** → Multiple sportsbook accounts

### Operational Risks
- **Injury data delays** → Multiple monitoring sources
- **System downtime** → Redundant infrastructure
- **Human error** → Automated safeguards, logging

---

*This roadmap serves as a complete reference for the MLB betting project. Each phase builds upon the previous one, with clear milestones and success criteria. The combination of ML baseline + RL adaptation addresses a genuine sequential learning problem while maintaining practical viability.*