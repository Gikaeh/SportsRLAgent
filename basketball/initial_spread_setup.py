from data_pipeline.basketball_data import BasketballData
from data_pipeline.prepare_data import NBATrainingDataPreparer
from model.model_spread import BasketballSpreadModel
from sklearn.model_selection import train_test_split

basketball_data = BasketballData()
basketball_data.getAllSeasonData()

preparer = NBATrainingDataPreparer(data_dir='././data/basketball')

# Prepare training data
training_data = preparer.prepareAllSeasons()

basketball_model = BasketballSpreadModel()

train_data, test_data = train_test_split(training_data, test_size=0.4, random_state=42)
val_data, test_data = train_test_split(test_data, test_size=0.5, random_state=42)

# Drop leakage columns (post-game data, identifiers, and season)
# Season is dropped to prevent data leakage - model should learn patterns, not season-specific trends
leakage_cols = basketball_model.getLeakageColumns()

train_data = train_data.drop(columns=[col for col in leakage_cols if col in train_data.columns])
val_data = val_data.drop(columns=[col for col in leakage_cols if col in val_data.columns])
test_data = test_data.drop(columns=[col for col in leakage_cols if col in test_data.columns])

# Separate features and target
X_train, y_train = train_data.drop('point_diff', axis=1), train_data['point_diff']
X_val, y_val = val_data.drop('point_diff', axis=1), val_data['point_diff']
X_test, y_test = test_data.drop('point_diff', axis=1), test_data['point_diff']

print("Training shape:", X_train.shape)
print("Validation shape:", X_val.shape)
print("Test shape:", X_test.shape)
print("Data types:", X_train.dtypes)

# Tune hyperparameters
print("\n" + "="*60)
print("HYPERPARAMETER TUNING")
print("="*60)

best_params = basketball_model.tuneHyperparameters(X_train, y_train, X_val, y_val, n_trials=100)

# Train the model with early stopping
print("\n" + "="*60)
print("TRAINING MODEL")
print("="*60)
basketball_model.trainWithBestParams(X_train, y_train, X_val, y_val, verbose=50)  # Show eval every 100 rounds
# basketball_model.train(X_train, y_train, X_val, y_val)

# Evaluate on validation set
val_mae, val_rmse, val_r2, val_within_3, val_within_5, val_within_7, removals = basketball_model.evaluate(X_val, y_val, X_train)

# Evaluate on test set
test_mae, test_rmse, test_r2, test_within_3, test_within_5, test_within_7 = basketball_model.evaluate(X_test, y_test)

basketball_model.saveModel('./models/basketball_spread_model.json')

# Generate diagnostic plots
basketball_model.plotDiagnostics(X_val, y_val, X_test, y_test, save_dir='./plots/basketball/spread')

# Print low importance features for manual removal
print("\n" + "="*60)
print("LOW IMPORTANCE FEATURES ANALYSIS")
print("="*60)
print(f"Features to Remove: {removals}")

# Print prediction summary
basketball_model.printPredictionSummary(X_test, y_test)