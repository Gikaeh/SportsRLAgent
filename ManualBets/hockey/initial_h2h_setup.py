from data_pipeline.hockey_data import HockeyData
from data_pipeline.prepare_data import NHLTrainingDataPreparer
from model.model_h2h import HockeyH2HModel
from sklearn.model_selection import train_test_split

hockey_data = HockeyData()
hockey_data.scrapeAllSeasons()

preparer = NHLTrainingDataPreparer()

# Prepare training data
training_data = preparer.prepareMultipleSeasons()

hockey_model = HockeyH2HModel()

train_data, test_data = train_test_split(training_data, test_size=0.4, random_state=42)
val_data, test_data = train_test_split(test_data, test_size=0.5, random_state=42)

# Drop leakage columns (post-game data, identifiers, and season)
# Season is dropped to prevent data leakage - model should learn patterns, not season-specific trends
leakage_cols = [
    'game_id', 'date', 'home_score', 'away_score', 'total_score',
    'season', 'home_team', 'away_team', 'goal_diff', 
] + hockey_model.getLeakageColumns()

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

best_params = hockey_model.tuneHyperparameters(X_train, y_train, X_val, y_val, n_trials=100, metric='logloss')

# Train the model with early stopping
print("\n" + "="*60)
print("TRAINING MODEL")
print("="*60)
hockey_model.trainWithBestParams(X_train, y_train, X_val, y_val, verbose=50)  # Show eval every 100 rounds

hockey_model.analyzeCalibration(y_val, hockey_model.predictProb(X_val)[:, 1])

# Evaluate on validation set
val_accuracy, val_brier, val_logloss, val_auc = hockey_model.evaluate(X_val, y_val)
print(f"\nValidation Metrics:")
print(f"Accuracy: {val_accuracy:.4f}")
print(f"Brier Score: {val_brier:.4f}")
print(f"Log Loss: {val_logloss:.4f}")
print(f"AUC-ROC: {val_auc:.4f}")

# Evaluate on test set
test_accuracy, test_brier, test_logloss, test_auc = hockey_model.evaluate(X_test, y_test)
print(f"\nTest Metrics:")
print(f"Accuracy: {test_accuracy:.4f}")
print(f"Brier Score: {test_brier:.4f}")
print(f"Log Loss: {test_logloss:.4f}")
print(f"AUC-ROC: {test_auc:.4f}")

hockey_model.saveModel('././models/hockey_h2h_model.json')

# Generate diagnostic plots
hockey_model.plotDiagnostics(X_val, y_val, X_test, y_test, save_dir='././plots/hockey/h2h')

# Print low importance features for manual removal
print("\n" + "="*60)
print("LOW IMPORTANCE FEATURES ANALYSIS")
print("="*60)
threshold = 0.01  # Adjust this threshold as needed
low_importance_features = hockey_model.printLowImportanceFeatures(threshold)

# Print prediction summary
hockey_model.printPredictionSummary(X_test, y_test)
