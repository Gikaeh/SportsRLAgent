import pandas as pd

from data_pipeline.basketball_data import BasketballData
from data_pipeline.prepare_data import NBATrainingDataPreparer
from model.model_h2h import BasketballH2HModel
from shared.splitting import chronologicalSplit

basketball_data = BasketballData()
basketball_data.getAllSeasonData()

preparer = NBATrainingDataPreparer(data_dir='././data/basketball')

# Prepare training data
training_data = preparer.prepareAllSeasons()

basketball_model = BasketballH2HModel()

# Chronological split (NOTES.md A2): earliest games train, then validation,
# latest games test. Random shuffling leaks future games into training.
training_data['date'] = pd.to_datetime(training_data['date'], utc=True).dt.tz_localize(None)
train_data, val_data, test_data = chronologicalSplit(
    training_data, date_col='date', test_frac=0.2, val_frac_of_test=0.5
)

print(f"Train: {train_data['date'].min().date()} -> {train_data['date'].max().date()}")
print(f"Val:   {val_data['date'].min().date()} -> {val_data['date'].max().date()}")
print(f"Test:  {test_data['date'].min().date()} -> {test_data['date'].max().date()}")

# Drop leakage columns (post-game data, identifiers, and season)
# Season is dropped to prevent data leakage - model should learn patterns, not season-specific trends
leakage_cols = basketball_model.getLeakageColumns()

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
# basketball_model.train(X_train, y_train, X_val, y_val)

basketball_model.analyzeCalibration(y_val, basketball_model.predictProb(X_val)[:, 1])

# Evaluate on validation set
val_accuracy, val_brier, val_logloss, val_auc, removals = basketball_model.evaluate(X_val, y_val, X_train)
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

print(f"\nLow Importance Features:")
print(f"Feature to remove: {removals}")

basketball_model.saveModel('././models/basketball_h2h_model.json')

# Generate diagnostic plots
basketball_model.plotDiagnostics(X_val, y_val, X_test, y_test, save_dir='././plots/basketball/h2h')

# Print prediction summary
basketball_model.printPredictionSummary(X_test, y_test)
