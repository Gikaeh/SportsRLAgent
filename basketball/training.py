from data_pipeline.basketball_data import BasketballData
from data_pipeline.prepare_data import NBATrainingDataPreparer
from model import BasketballModel
from sklearn.model_selection import train_test_split

basketball_data = BasketballData()
basketball_data.getAllSeasonData()

preparer = NBATrainingDataPreparer(data_dir='././data/basketball')

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
leakage_cols = ['game_id', 'date', 'home_score', 'away_score', 'season', 'home_team', 'away_team']
train_data = train_data.drop(columns=[col for col in leakage_cols if col in train_data.columns])
val_data = val_data.drop(columns=[col for col in leakage_cols if col in val_data.columns])
test_data = test_data.drop(columns=[col for col in leakage_cols if col in test_data.columns])

# Separate features and target
X_train, y_train = train_data.drop('home_won', axis=1), train_data['home_won']
X_val, y_val = val_data.drop('home_won', axis=1), val_data['home_won']
X_test, y_test = test_data.drop('home_won', axis=1), test_data['home_won']

print("Training shape:", X_train.shape)
print("Validation shape:", X_val.shape)
print("Test shape:", X_test.shape)
print("Data types:", X_train.dtypes)

# Tune hyperparameters
print("\n" + "="*60)
print("HYPERPARAMETER TUNING")
print("="*60)

best_params = basketball_model.tuneHyperparameters(X_train, y_train, X_val, y_val, n_trials=100, metric='logloss')

# Train the model with early stopping
print("\n" + "="*60)
print("TRAINING MODEL")
print("="*60)
basketball_model.trainWithBestParams(X_train, y_train, X_val, y_val, verbose=50)  # Show eval every 100 rounds

basketball_model.analyzeCalibration(y_val, basketball_model.predict_proba(X_val)[:, 1])

# Evaluate on validation set
val_accuracy, val_brier, val_logloss, val_auc = basketball_model.evaluate(X_val, y_val)
print(f"\nValidation Metrics:")
print(f"Accuracy: {val_accuracy:.4f}")
print(f"Brier Score: {val_brier:.4f}")
print(f"Log Loss: {val_logloss:.4f}")
print(f"AUC-ROC: {val_auc:.4f}")

# Evaluate on test set
test_accuracy, test_brier, test_logloss, test_auc = basketball_model.evaluate(X_test, y_test)
print(f"\nTest Metrics:")
print(f"Accuracy: {test_accuracy:.4f}")
print(f"Brier Score: {test_brier:.4f}")
print(f"Log Loss: {test_logloss:.4f}")
print(f"AUC-ROC: {test_auc:.4f}")

basketball_model.saveModel('././models/basketball_model.json')

# Generate diagnostic plots
basketball_model.plotDiagnostics(X_val, y_val, X_test, y_test, save_dir='././plots/basketball')

# Print low importance features for manual removal
print("\n" + "="*60)
print("LOW IMPORTANCE FEATURES ANALYSIS")
print("="*60)
threshold = 0.01  # Adjust this threshold as needed
low_importance_features = basketball_model.printLowImportanceFeatures(threshold)

# Print prediction summary
basketball_model.printPredictionSummary(X_test, y_test)
