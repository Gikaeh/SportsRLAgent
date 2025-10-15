from basketball_data import BasketballData
from prepare_training_data import NBATrainingDataPreparer
from model import BasketballModel
from sklearn.model_selection import train_test_split
import numpy as np

basketball_data = BasketballData()
basketball_data.getAllSeasonData()

preparer = NBATrainingDataPreparer(data_dir='./data/basketball')

print("NBA Training Data Preparation - Phase 1")
print("="*60)
print("Preparing STREAMLINED 28-feature dataset:")
print("  - Team Performance (8): L10 wins, net rating, PPG, opp PPG")
print("  - Game Context (4): Rest days, back-to-back flags")
print("  - Player Aggregates (12): Top 3/5/6 stats, star quality, depth")
print("  - Shooting Efficiency (4): FG% and 3P% L10")
print("="*60)

# Prepare training data
training_data = preparer.prepareAllSeasons()

basketball_model = BasketballModel()

train_data, test_data = train_test_split(training_data, test_size=0.4, random_state=42)
val_data, test_data = train_test_split(test_data, test_size=0.5, random_state=42)

# Drop leakage columns (post-game data, identifiers, and season)
# Season is dropped to prevent data leakage - model should learn patterns, not season-specific trends
leakage_cols = ['game_id', 'date', 'home_score', 'away_score', 'season']
train_data = train_data.drop(columns=[col for col in leakage_cols if col in train_data.columns])
val_data = val_data.drop(columns=[col for col in leakage_cols if col in val_data.columns])
test_data = test_data.drop(columns=[col for col in leakage_cols if col in test_data.columns])

# Separate features and target
X_train, y_train = train_data.drop('home_won', axis=1), train_data['home_won']
X_val, y_val = val_data.drop('home_won', axis=1), val_data['home_won']
X_test, y_test = test_data.drop('home_won', axis=1), test_data['home_won']

# Convert categorical columns (team names) to category dtype
categorical_cols = X_train.select_dtypes(exclude=np.number).columns.tolist()
for col in categorical_cols:
    X_train[col] = X_train[col].astype('category')
    X_val[col] = X_val[col].astype('category')
    X_test[col] = X_test[col].astype('category')

print("Training shape:", X_train.shape)
print("Validation shape:", X_val.shape)
print("Test shape:", X_test.shape)

# Tune hyperparameters
print("\n" + "="*60)
print("HYPERPARAMETER TUNING")
print("="*60)

best_params = basketball_model.tune_hyperparameters(X_train, y_train, X_val, y_val, n_trials=50, metric='logloss')

# Train the model with early stopping
print("\n" + "="*60)
print("TRAINING MODEL")
print("="*60)
basketball_model.train_with_best_params(X_train, y_train, X_val, y_val, verbose=50)  # Show eval every 100 rounds

basketball_model.calibrate_probabilities(X_val, y_val, method='isotonic')

# Evaluate on validation set
val_accuracy, val_brier, val_logloss, val_auc = basketball_model.evaluate(X_val, y_val, use_calibrated=True)
print(f"\nValidation Metrics:")
print(f"Accuracy: {val_accuracy:.4f}")
print(f"Brier Score: {val_brier:.4f}")
print(f"Log Loss: {val_logloss:.4f}")
print(f"AUC-ROC: {val_auc:.4f}")

# Evaluate on test set
test_accuracy, test_brier, test_logloss, test_auc = basketball_model.evaluate(X_test, y_test, use_calibrated=True)
print(f"\nTest Metrics:")
print(f"Accuracy: {test_accuracy:.4f}")
print(f"Brier Score: {test_brier:.4f}")
print(f"Log Loss: {test_logloss:.4f}")
print(f"AUC-ROC: {test_auc:.4f}")

# Generate diagnostic plots
basketball_model.plot_diagnostics(X_val, y_val, X_test, y_test, save_dir='./plots/basketball', use_calibrated=True)

# Print prediction summary
basketball_model.print_prediction_summary(X_test, y_test, use_calibrated=True)
