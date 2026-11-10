from data_pipeline.hockey_data import HockeyData
from data_pipeline.prepare_data import NHLTrainingDataPreparer
from model.model_total import HockeyTotalModel
from sklearn.model_selection import train_test_split

hockey_data = HockeyData()
hockey_data.scrapeAllSeasons()

preparer = NHLTrainingDataPreparer()

# Prepare training data
training_data = preparer.prepareMultipleSeasons()

hockey_model = HockeyTotalModel()

train_data, test_data = train_test_split(training_data, test_size=0.4, random_state=42)
val_data, test_data = train_test_split(test_data, test_size=0.5, random_state=42)

# Drop leakage columns (post-game data, identifiers, and season)
# Season is dropped to prevent data leakage - model should learn patterns, not season-specific trends
leakage_cols = [
    'game_id', 'date', 'home_score', 'away_score', 'goal_diff',
    'season', 'home_team', 'away_team', 'home_won', 
] + hockey_model.getLeakageColumns()

train_data = train_data.drop(columns=[col for col in leakage_cols if col in train_data.columns])
val_data = val_data.drop(columns=[col for col in leakage_cols if col in val_data.columns])
test_data = test_data.drop(columns=[col for col in leakage_cols if col in test_data.columns])

# Separate features and target
X_train, y_train = train_data.drop('total_score', axis=1), train_data['total_score']
X_val, y_val = val_data.drop('total_score', axis=1), val_data['total_score']
X_test, y_test = test_data.drop('total_score', axis=1), test_data['total_score']

print("Training shape:", X_train.shape)
print("Validation shape:", X_val.shape)
print("Test shape:", X_test.shape)
print("Data types:", X_train.dtypes)

# Tune hyperparameters
print("\n" + "="*60)
print("HYPERPARAMETER TUNING")
print("="*60)

best_params = hockey_model.tuneHyperparameters(X_train, y_train, X_val, y_val, n_trials=100)

# Train the model with early stopping
print("\n" + "="*60)
print("TRAINING MODEL")
print("="*60)
hockey_model.trainWithBestParams(X_train, y_train, X_val, y_val, verbose=50)  # Show eval every 100 rounds

# Evaluate on validation set
val_mae, val_rmse, val_r2, val_within_3, val_within_5, val_within_10 = hockey_model.evaluate(X_val, y_val)

# Evaluate on test set
test_mae, test_rmse, test_r2, test_within_3, test_within_5, test_within_10 = hockey_model.evaluate(X_test, y_test)

hockey_model.saveModel('./models/hockey_total_model.json')

# Generate diagnostic plots
hockey_model.plotDiagnostics(X_val, y_val, X_test, y_test, save_dir='./plots/hockey/total')

# Print low importance features for manual removal
print("\n" + "="*60)
print("LOW IMPORTANCE FEATURES ANALYSIS")
print("="*60)
threshold = 0.01  # Adjust this threshold as needed
low_importance_features = hockey_model.printLowImportanceFeatures(threshold)

# Print prediction summary
hockey_model.printPredictionSummary(X_test, y_test)
