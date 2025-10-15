from prepare_training_data import NBATrainingDataPreparer
from basketball_data import BasketballData
from ensemble_model import EnsembleBasketballModel
from sklearn.model_selection import train_test_split
import pandas as pd
import numpy as np

# Load training data
print("="*60)
print("LOADING TRAINING DATA")
print("="*60)

training_data = pd.read_csv('./data/training_data/basketball/phase1/all_seasons_training_data.csv')

# Separate features and target
X = training_data.drop(['game_id', 'date', 'season', 'home_team', 'away_team', 'home_score', 'away_score', 'home_won'], axis=1)
y = training_data['home_won']

# Convert categorical columns
for col in X.columns:
    if X[col].dtype == 'object':
        X[col] = X[col].astype('category')

# Split data: 60% train, 20% validation, 20% test
X_train, X_temp, y_train, y_temp = train_test_split(X, y, test_size=0.4, random_state=42, shuffle=False)
X_val, X_test, y_val, y_test = train_test_split(X_temp, y_temp, test_size=0.5, random_state=42, shuffle=False)

print(f"\nTraining shape: {X_train.shape}")
print(f"Validation shape: {X_val.shape}")
print(f"Test shape: {X_test.shape}")

# Initialize ensemble
ensemble = EnsembleBasketballModel()

# Add models to ensemble
print("\nAdding models to ensemble...")
ensemble.add_xgboost()  # Uses tuned parameters from your best run
ensemble.add_lightgbm()
ensemble.add_random_forest()
ensemble.add_logistic_regression()  # Baseline

# Train all models
ensemble.train_all(X_train, y_train, X_val, y_val, verbose=True)

# Optimize ensemble weights
print("\n" + "="*60)
print("OPTIMIZING ENSEMBLE WEIGHTS")
print("="*60)
ensemble.optimize_weights(X_val, y_val, metric='brier')

# Evaluate uncalibrated ensemble
print("\n" + "="*60)
print("UNCALIBRATED ENSEMBLE PERFORMANCE")
print("="*60)

val_acc, val_brier, val_logloss, val_auc = ensemble.evaluate(X_val, y_val, use_calibrated=False)
print(f"\nValidation Metrics:")
print(f"Accuracy: {val_acc:.4f}")
print(f"Brier Score: {val_brier:.4f}")
print(f"Log Loss: {val_logloss:.4f}")
print(f"AUC-ROC: {val_auc:.4f}")

test_acc, test_brier, test_logloss, test_auc = ensemble.evaluate(X_test, y_test, use_calibrated=False)
print(f"\nTest Metrics:")
print(f"Accuracy: {test_acc:.4f}")
print(f"Brier Score: {test_brier:.4f}")
print(f"Log Loss: {test_logloss:.4f}")
print(f"AUC-ROC: {test_auc:.4f}")

ensemble.print_prediction_summary(X_test, y_test, use_calibrated=False)

# Calibrate ensemble to fix home bias
print("\n" + "="*60)
print("CALIBRATING ENSEMBLE")
print("="*60)
ensemble.calibrate(X_val, y_val, method='isotonic')

# Evaluate calibrated ensemble
print("\n" + "="*60)
print("CALIBRATED ENSEMBLE PERFORMANCE")
print("="*60)

val_acc_cal, val_brier_cal, val_logloss_cal, val_auc_cal = ensemble.evaluate(X_val, y_val, use_calibrated=True)
print(f"\nValidation Metrics (Calibrated):")
print(f"Accuracy: {val_acc_cal:.4f}")
print(f"Brier Score: {val_brier_cal:.4f}")
print(f"Log Loss: {val_logloss_cal:.4f}")
print(f"AUC-ROC: {val_auc_cal:.4f}")

test_acc_cal, test_brier_cal, test_logloss_cal, test_auc_cal = ensemble.evaluate(X_test, y_test, use_calibrated=True)
print(f"\nTest Metrics (Calibrated):")
print(f"Accuracy: {test_acc_cal:.4f}")
print(f"Brier Score: {test_brier_cal:.4f}")
print(f"Log Loss: {test_logloss_cal:.4f}")
print(f"AUC-ROC: {test_auc_cal:.4f}")

ensemble.print_prediction_summary(X_test, y_test, use_calibrated=True)

# Compare improvements
print("\n" + "="*60)
print("CALIBRATION IMPROVEMENTS")
print("="*60)
print(f"\nBrier Score Improvement: {test_brier - test_brier_cal:.4f}")
print(f"Log Loss Improvement: {test_logloss - test_logloss_cal:.4f}")
print(f"Accuracy Change: {test_acc_cal - test_acc:.4f}")

# Show individual model contributions
print("\n" + "="*60)
print("ENSEMBLE WEIGHTS")
print("="*60)
for name, weight in ensemble.weights.items():
    print(f"{name}: {weight:.3f} ({weight*100:.1f}%)")
