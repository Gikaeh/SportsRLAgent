import xgboost as xgb
import lightgbm as lgb
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.calibration import CalibratedClassifierCV
import numpy as np
import pandas as pd

class EnsembleBasketballModel:
    def __init__(self):
        self.models = {}
        self.weights = None
        self.calibrated_ensemble = None
        
    def add_xgboost(self, params=None):
        """Add XGBoost to ensemble."""
        if params is None:
            params = {
                'max_depth': 9,
                'learning_rate': 0.014,
                'subsample': 0.85,
                'colsample_bytree': 0.64,
                'min_child_weight': 6,
                'gamma': 2.98,
                'reg_alpha': 7.51,
                'reg_lambda': 8.33,
                'n_estimators': 1000,
                'early_stopping_rounds': 50,
                'use_label_encoder': False,
                'eval_metric': 'logloss',
                'tree_method': 'hist',
                'enable_categorical': True,
                'random_state': 42
            }
        self.models['xgboost'] = xgb.XGBClassifier(**params)
        
    def add_lightgbm(self, params=None):
        """Add LightGBM to ensemble."""
        if params is None:
            params = {
                'max_depth': 8,
                'learning_rate': 0.02,
                'subsample': 0.8,
                'colsample_bytree': 0.7,
                'min_child_weight': 5,
                'reg_alpha': 5.0,
                'reg_lambda': 7.0,
                'n_estimators': 1000,
                'random_state': 42,
                'verbose': -1
            }
        self.models['lightgbm'] = lgb.LGBMClassifier(**params)
        
    def add_random_forest(self, params=None):
        """Add Random Forest to ensemble."""
        if params is None:
            params = {
                'n_estimators': 500,
                'max_depth': 12,
                'min_samples_split': 10,
                'min_samples_leaf': 5,
                'max_features': 'sqrt',
                'random_state': 42,
                'n_jobs': -1
            }
        self.models['random_forest'] = RandomForestClassifier(**params)
        
    def add_logistic_regression(self):
        """Add Logistic Regression as baseline."""
        self.models['logistic'] = LogisticRegression(
            max_iter=1000,
            random_state=42
        )
    
    def train_all(self, X_train, y_train, X_val=None, y_val=None, verbose=True):
        """Train all models in the ensemble."""
        print("\n" + "="*60)
        print("TRAINING ENSEMBLE MODELS")
        print("="*60)
        
        for name, model in self.models.items():
            print(f"\nTraining {name}...")
            
            if name in ['xgboost', 'lightgbm'] and X_val is not None:
                model.fit(
                    X_train, y_train,
                    eval_set=[(X_val, y_val)],
                    verbose=False
                )
            else:
                model.fit(X_train, y_train)
            
            if verbose and X_val is not None:
                val_proba = model.predict_proba(X_val)[:, 1]
                val_pred = model.predict(X_val)
                
                acc = accuracy_score(y_val, val_pred)
                brier = brier_score_loss(y_val, val_proba)
                logloss = log_loss(y_val, val_proba)
                auc = roc_auc_score(y_val, val_proba)
                
                print(f"  Accuracy: {acc:.4f}")
                print(f"  Brier: {brier:.4f}")
                print(f"  Log Loss: {logloss:.4f}")
                print(f"  AUC: {auc:.4f}")
    
    def optimize_weights(self, X_val, y_val, metric='brier'):
        """Find optimal weights for ensemble using validation set."""
        print(f"\nOptimizing ensemble weights based on {metric}...")
        
        # Get predictions from all models
        predictions = {}
        for name, model in self.models.items():
            predictions[name] = model.predict_proba(X_val)[:, 1]
        
        # Grid search for best weights
        best_score = float('inf') if metric in ['brier', 'logloss'] else float('-inf')
        best_weights = None
        
        # Try different weight combinations
        from itertools import product
        weight_options = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        
        model_names = list(predictions.keys())
        n_models = len(model_names)
        
        print(f"Testing weight combinations for {n_models} models...")
        
        for weights in product(weight_options, repeat=n_models):
            if sum(weights) == 0:
                continue
            
            # Normalize weights
            normalized_weights = np.array(weights) / sum(weights)
            
            # Calculate ensemble prediction
            ensemble_proba = sum(predictions[name] * w 
                               for name, w in zip(model_names, normalized_weights))
            
            # Calculate metric
            if metric == 'brier':
                score = brier_score_loss(y_val, ensemble_proba)
            elif metric == 'logloss':
                score = log_loss(y_val, ensemble_proba)
            elif metric == 'auc':
                score = -roc_auc_score(y_val, ensemble_proba)
            elif metric == 'accuracy':
                score = -accuracy_score(y_val, (ensemble_proba > 0.5).astype(int))
            
            # Update best
            if metric in ['brier', 'logloss']:
                if score < best_score:
                    best_score = score
                    best_weights = dict(zip(model_names, normalized_weights))
            else:
                if score > best_score:
                    best_score = score
                    best_weights = dict(zip(model_names, normalized_weights))
        
        self.weights = best_weights
        
        print(f"\nOptimal weights found:")
        for name, weight in self.weights.items():
            print(f"  {name}: {weight:.3f}")
        print(f"Best {metric}: {best_score:.4f}")
        
        return self.weights
    
    def predict_proba(self, X):
        """Predict probabilities using weighted ensemble."""
        if self.weights is None:
            # Equal weights if not optimized
            self.weights = {name: 1.0/len(self.models) for name in self.models.keys()}
        
        ensemble_proba = np.zeros(len(X))
        for name, model in self.models.items():
            proba = model.predict_proba(X)[:, 1]
            ensemble_proba += proba * self.weights[name]
        
        # Return in sklearn format
        return np.column_stack([1 - ensemble_proba, ensemble_proba])
    
    def predict(self, X):
        """Predict class labels."""
        proba = self.predict_proba(X)[:, 1]
        return (proba > 0.5).astype(int)
    
    def calibrate(self, X_val, y_val, method='isotonic'):
        """Calibrate ensemble probabilities to fix bias."""
        print(f"\nCalibrating ensemble using {method} regression...")
        
        # Create a wrapper for the ensemble
        class EnsembleWrapper:
            def __init__(self, ensemble):
                self.ensemble = ensemble
            
            def fit(self, X, y):
                return self
            
            def predict_proba(self, X):
                return self.ensemble.predict_proba(X)
        
        wrapper = EnsembleWrapper(self)
        
        self.calibrated_ensemble = CalibratedClassifierCV(
            wrapper,
            method=method,
            cv='prefit'
        )
        
        self.calibrated_ensemble.fit(X_val, y_val)
        
        # Compare before/after
        uncal_proba = self.predict_proba(X_val)[:, 1]
        cal_proba = self.calibrated_ensemble.predict_proba(X_val)[:, 1]
        
        uncal_brier = brier_score_loss(y_val, uncal_proba)
        cal_brier = brier_score_loss(y_val, cal_proba)
        
        print(f"Uncalibrated Brier Score: {uncal_brier:.4f}")
        print(f"Calibrated Brier Score: {cal_brier:.4f}")
        print(f"Improvement: {uncal_brier - cal_brier:.4f}")
        
        return self.calibrated_ensemble
    
    def predict_proba_calibrated(self, X):
        """Use calibrated ensemble for predictions."""
        if self.calibrated_ensemble is not None:
            return self.calibrated_ensemble.predict_proba(X)
        else:
            return self.predict_proba(X)
    
    def evaluate(self, X_test, y_test, use_calibrated=False):
        """Evaluate ensemble performance."""
        if use_calibrated and self.calibrated_ensemble is not None:
            proba = self.calibrated_ensemble.predict_proba(X_test)[:, 1]
        else:
            proba = self.predict_proba(X_test)[:, 1]
        
        pred = (proba > 0.5).astype(int)
        
        accuracy = accuracy_score(y_test, pred)
        brier = brier_score_loss(y_test, proba)
        logloss = log_loss(y_test, proba)
        auc = roc_auc_score(y_test, proba)
        
        return accuracy, brier, logloss, auc
    
    def print_prediction_summary(self, X_test, y_test, use_calibrated=False):
        """Print detailed prediction summary."""
        if use_calibrated and self.calibrated_ensemble is not None:
            proba = self.calibrated_ensemble.predict_proba(X_test)[:, 1]
        else:
            proba = self.predict_proba(X_test)[:, 1]
        
        pred = (proba > 0.5).astype(int)
        
        print("\n" + "="*60)
        print("ENSEMBLE PREDICTION SUMMARY")
        print("="*60)
        
        # Overall stats
        print(f"\nTotal Predictions: {len(pred)}")
        print(f"Predicted Home Wins: {pred.sum()} ({pred.sum()/len(pred)*100:.1f}%)")
        print(f"Predicted Away Wins: {(1-pred).sum()} ({(1-pred).sum()/len(pred)*100:.1f}%)")
        print(f"Actual Home Wins: {y_test.sum()} ({y_test.sum()/len(y_test)*100:.1f}%)")
        
        # Confidence distribution
        confidence = np.abs(proba - 0.5) * 2
        print(f"\nAverage Confidence: {confidence.mean():.3f}")
        print(f"High Confidence (>0.7): {(confidence > 0.7).sum()} predictions ({(confidence > 0.7).sum()/len(confidence)*100:.1f}%)")
        print(f"Medium Confidence (0.3-0.7): {((confidence >= 0.3) & (confidence <= 0.7)).sum()} predictions")
        print(f"Low Confidence (<0.3): {(confidence < 0.3).sum()} predictions ({(confidence < 0.3).sum()/len(confidence)*100:.1f}%)")
        
        # Accuracy by confidence
        correct = (pred == y_test).astype(int)
        high_conf_mask = confidence > 0.7
        if high_conf_mask.sum() > 0:
            print(f"\nAccuracy on High Confidence Predictions: {correct[high_conf_mask].mean():.3f}")
        
        print("="*60)
