
# MLB Betting Project: Corrected Implementation Roadmap

**ML Baseline → RL Injury-Adaptive Betting System**

## Project Overview

 **Goal** : Build a betting system that uses ML for base predictions and RL to dynamically adjust confidence based on real-time player availability/injuries.

 **Strategy** :

* **Phase 1-2** : Build profitable ML baseline with static features only
* **Phase 3** : Add injury data collection and RL system when actually needed
* **Phase 4-5** : Integration and production deployment

 **Key Insight** : Prove the foundation works before adding complexity.

---

## Phase 1: Minimal Data Foundation (Weeks 1-3)

### 1.1 Core Data Collection (Priority Order)

**Priority 1: Essential Betting Data**

* Single sportsbook for ML baseline (BetOnline - sharpest available)
* Historical moneyline odds (2020-2024)
* Game results and scores
* Data structure:

```
columns = ['game_id', 'date', 'home_team', 'away_team', 
           'betonline_opening_home_ml', 'betonline_closing_home_ml',
           'betonline_opening_away_ml', 'betonline_closing_away_ml',
           'home_score', 'away_score', 'home_won']
```

**Priority 2: Basic Team Performance**

* Team wins/losses and recent form (last 10 games)
* Runs scored/allowed per game (season and L10)
* Team ERA and basic pitching stats (season and L10)
* Home/away record splits

**Priority 3: Starting Pitcher Stats**

* Season stats: ERA, WHIP, K/9, BB/9, innings pitched
* Recent form: Last 5 starts performance
* Career stats vs opposing team (if available)

**Priority 4: Game Context**

* Park factors (using Baseball Savant scraper)
* Weather data: temperature, wind speed/direction
* Game timing: day/night, rest days for teams

### 1.2 Data Pipeline Setup

```python
# One-time historical backfill
def backfill_historical_data():
    # 1. Scrape 2020-2024 game results
    # 2. Collect BetOnline historical odds
    # 3. Gather team/pitcher stats by season
    # 4. Park factors for each stadium/year
  
# Simple validation
def validate_data_quality():
    # Check for missing games, odd score combinations
    # Validate odds format (American to probability)
    # Ensure no future data leakage
```

### 1.3 Success Criteria for Phase 1

* Complete 2020-2024 game dataset (11,000+ games)
* <2% missing critical features (odds, scores, starting pitchers)
* Clean team performance metrics for all 30 teams
* Functional park factor data for all stadiums

**EXPLICITLY EXCLUDED FROM PHASE 1:**

* ❌ Injury data collection (not needed until Phase 3)
* ❌ Multiple sportsbook odds (not needed until Phase 3)
* ❌ Player-level availability tracking (RL component)
* ❌ Complex real-time data pipelines

---

## Phase 2: ML Baseline Model (Weeks 4-6)

### 2.1 Feature Engineering

**Core Features (Static Game Data Only):**

```python
ml_features = [
    # Pitching matchup
    'home_sp_era', 'away_sp_era', 'home_sp_whip', 'away_sp_whip',
    'home_sp_era_l5', 'away_sp_era_l5',
  
    # Team recent performance  
    'home_wins_l10', 'away_wins_l10', 'home_runs_l10', 'away_runs_l10',
    'home_era_l10', 'away_era_l10',
  
    # Game context
    'temperature', 'park_run_factor', 'is_day_game',
    'home_rest_days', 'away_rest_days',
  
    # Market signals (single book only)
    'home_implied_prob', 'line_movement'
]
```

### 2.2 Model Development

**Model Candidates:**

1. **XGBoost** - Primary choice for tabular data
2. **Random Forest** - Interpretability backup
3. **Logistic Regression** - Simple baseline

**Training Strategy:**

* Time-based splits: Train 2020-2022, Validate 2023, Test 2024
* Walk-forward validation within training period
* No look-ahead bias in feature creation

### 2.3 Success Metrics

**Technical Performance:**

* Accuracy >53% (break-even threshold at -110 odds)
* Log loss <0.68 (well-calibrated probabilities)
* ROC AUC >0.55

**Business Performance:**

* Positive ROI on 2024 test data
* Kelly criterion bet sizing
* Maximum drawdown <20%

### 2.4 Phase 2 Deliverable

**Working ML betting system that:**

* Predicts game outcomes with >53% accuracy
* Makes profitable betting decisions on historical data
* Uses only static, easily obtainable features
* Provides confidence intervals for predictions

---

## Phase 3: RL System + Injury Data (Weeks 7-10)

### 3.1 NOW Add Injury Data Collection

**Real-Time Player Monitoring:**

* Daily injury reports (ESPN, MLB.com, CBS Sports)
* Starting lineup announcements (~2 hours before games)
* Player importance classification system

**Data Structure:**

```python
injury_data = [
    'player_name', 'team', 'date', 'injury_status', 
    'expected_return', 'games_missed', 'position', 'importance_weight'
]

lineup_data = [
    'game_id', 'team', 'batting_order', 'player_name', 
    'position', 'vs_handedness_ops'
]
```

### 3.2 RL Problem Definition

**State Space:**

```python
rl_state = [
    base_ml_confidence,           # From Phase 2 model
    home_key_player_statuses,     # 5 players × 2 features  
    away_key_player_statuses,     # 5 players × 2 features
    learned_player_weights,       # Historical impact scores
    recent_rl_accuracy,          # How well is RL performing?
    market_context               # Basic market signals
]
# Total: ~20-25 dimensional state space
```

**Action Space:**
Confidence adjustments: [-1.0, -0.9, ..., +0.9, +1.0] (21 actions)

**Reward Function:**

```python
def calculate_reward(base_confidence, adjusted_confidence, actual_result):
    base_error = abs(base_confidence - actual_result)
    adjusted_error = abs(adjusted_confidence - actual_result)
  
    improvement = base_error - adjusted_error
  
    if improvement > 0.1:
        return +2      # Significant improvement
    elif improvement > 0.05:
        return +1      # Moderate improvement  
    elif improvement > -0.05:
        return 0       # No meaningful change
    else:
        return -1      # Made prediction worse
```

### 3.3 RL Architecture

**Deep Q-Network Implementation:**

* Input: State vector (25 dimensions)
* Hidden layers: [128, 64, 32] with ReLU activation
* Output: Q-values for 21 possible confidence adjustments
* Experience replay buffer (10,000 transitions)
* Target network updated every 1000 steps

### 3.4 Success Criteria for Phase 3

**Technical:**

* RL agent learns to make meaningful confidence adjustments
* Player impact weights converge to reasonable values
* System maintains stability during training

**Business:**

* RL enhancement improves ROI by >1% over ML baseline
* No catastrophic confidence adjustments (>±0.5)
* Successful adaptation to major injury news

---

## Phase 4: Multi-Book Integration & Backtesting (Weeks 11-12)

### 4.1 Expand Betting Data

**NOW Add Multiple Sportsbooks:**

* Sharp books: BetOnline, LowVig (training comparison)
* Soft books: DraftKings, BetMGM (betting targets)
* Line shopping optimization

**Market Efficiency Features:**

```python
multi_book_features = [
    'sharp_consensus', 'public_consensus', 'sharp_public_diff',
    'best_home_odds', 'best_away_odds', 'market_disagreement',
    'line_shopping_value'
]
```

### 4.2 Complete System Integration

**Betting Decision Pipeline:**

```python
def make_betting_decision(game_data, current_date):
    # 1. Get base ML prediction (trained on sharp book)
    base_confidence = ml_model.predict_proba(game_data)[0][1]
  
    # 2. Get current player statuses  
    player_statuses = injury_tracker.get_status(current_date)
  
    # 3. RL confidence adjustment
    rl_state = build_rl_state(base_confidence, game_data, player_statuses)
    adjustment = rl_agent.choose_action(rl_state)
    final_confidence = np.clip(base_confidence + adjustment, 0.01, 0.99)
  
    # 4. Find best available odds (line shopping)
    best_odds = find_best_odds_across_books(game_data)
  
    # 5. Calculate betting edge and size
    edge = calculate_betting_edge(final_confidence, best_odds)
    if edge > 0.05:  # 5% minimum edge
        bet_size = kelly_criterion(final_confidence, best_odds)
        return {'bet': True, 'size': bet_size, 'book': best_book}
    else:
        return {'bet': False}
```

### 4.3 Backtesting Framework

**Historical Walk-Forward Testing:**

* Simulate real-time injury data discovery
* Account for line shopping time and transaction costs
* Test multiple bet sizing strategies
* Risk management stress testing

**Performance Comparison:**

* ML-only baseline performance
* ML + RL performance
* Statistical significance testing
* Risk-adjusted returns (Sharpe ratio)

---

## Phase 5: Production Deployment (Weeks 13-14)

### 5.1 Production Infrastructure

**Daily Automated Pipeline:**

```python
# 6:00 AM: Update injury reports and lineup changes
# 10:00 AM: Generate predictions for today's games  
# 2:00 PM: Final injury/lineup check
# 3:00 PM: Place bets (games typically start 7 PM)
# 11:00 PM: Collect results and update models
```

**System Components:**

* PostgreSQL: Historical data storage
* Redis: Real-time odds and injury caching
* Docker: Containerized deployment
* Monitoring: System health and model performance
* Alerting: Critical injury news, model anomalies

### 5.2 Risk Management

**Automated Safeguards:**

* Maximum bet size: 2% of bankroll per game
* Daily loss limit: Stop at 5% bankroll drawdown
* Confidence thresholds: Only bet games >60% final confidence
* Manual override: Human can disable system
* RL adjustment caps: ±0.3 maximum confidence adjustment

### 5.3 Success Criteria for Production

**6-Month Live Performance Targets:**

* Positive ROI (>3% minimum)
* Maximum drawdown <15%
* System uptime >99% during betting hours
* Successful handling of major injury situations

---

## Implementation Checklist

### Phase 1: Minimal Data Foundation

* [ ] Historical game results (2020-2024)
* [ ] BetOnline odds data (single book only)
* [ ] Team performance statistics
* [ ] Starting pitcher stats
* [ ] Park factors and weather data
* [ ] Data quality validation

### Phase 2: ML Baseline Model

* [ ] Feature engineering pipeline
* [ ] ML model training and validation
* [ ] Backtesting on historical data
* [ ] Performance evaluation (>53% accuracy)
* [ ] Working betting decision system
* [ ] Profitability confirmation

### Phase 3: RL + Injury System

* [ ] Injury data collection infrastructure
* [ ] Player importance classification
* [ ] RL environment and agent implementation
* [ ] RL training and validation
* [ ] Player impact learning system
* [ ] RL performance evaluation vs ML baseline

### Phase 4: Multi-Book Integration

* [ ] Additional sportsbook data collection
* [ ] Line shopping optimization
* [ ] Complete system integration
* [ ] Comprehensive backtesting
* [ ] Risk assessment and stress testing
* [ ] Performance comparison and validation

### Phase 5: Production Deployment

* [ ] Production infrastructure setup
* [ ] Automated daily pipelines
* [ ] Monitoring and alerting systems
* [ ] Risk management implementation
* [ ] Live performance tracking
* [ ] Continuous improvement process

---

## Expected Outcomes

### Realistic Scenario (Target)

* **Phase 2 ML Baseline** : 55% accuracy, 4% annual ROI
* **Phase 3 RL Enhancement** : +2% ROI improvement
* **Total System** : 6% annual ROI with <15% max drawdown

### Conservative Scenario (Minimum Acceptable)

* **Phase 2 ML Baseline** : 53% accuracy, 1% annual ROI
* **Phase 3 RL Enhancement** : +1% ROI improvement
* **Total System** : 2% annual ROI

### Stretch Goal (Optimistic)

* **Phase 2 ML Baseline** : 57% accuracy, 7% annual ROI
* **Phase 3 RL Enhancement** : +3% ROI improvement
* **Total System** : 10% annual ROI

---

## Technology Stack

**Core Technologies:**

* Python 3.9+ (primary language)
* PostgreSQL (historical data)
* Redis (real-time caching)
* PyTorch (RL implementation)
* XGBoost/Scikit-learn (ML models)
* Docker (deployment)

**Data Sources:**

* The Odds API (betting lines)
* Baseball-Reference (historical stats)
* Baseball Savant (park factors)
* ESPN/MLB.com (injury reports - Phase 3 only)

---

## Risk Factors & Mitigation

**Project Risks:**

* **Scope creep** → Strict phase boundaries, resist feature additions
* **Data complexity** → Start minimal, add complexity only when needed
* **Overfitting** → Rigorous time-based validation, walk-forward testing

**Market Risks:**

* **Line movement** → Real-time monitoring in production phase
* **Market efficiency** → Continuous model evaluation and updates
* **Betting limits** → Multiple sportsbook accounts in Phase 4

**Technical Risks:**

* **RL instability** → Conservative exploration, experience replay
* **Data source reliability** → Multiple backup sources
* **System downtime** → Redundant infrastructure in production

---

## Key Improvements from Original Roadmap

1. **Clear Sequential Logic** : Each phase builds naturally on the previous
2. **Immediate Value** : Working profitable system after Phase 2
3. **Reduced Complexity** : No unused data collection in early phases
4. **Risk Management** : Can stop at any phase with working system
5. **Realistic Scope** : Focus on core functionality before advanced features

*This corrected roadmap prioritizes building a solid foundation before adding complexity. Each phase delivers immediate value and can serve as a natural stopping point if resources or time become constrained.*
