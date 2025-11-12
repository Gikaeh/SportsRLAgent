import xgboost as xgb
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score, roc_curve
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
import optuna
from optuna.samplers import TPESampler

class BasketballH2HModel:
    def __init__(self, n_estimators=1000, early_stopping_rounds=50, **kwargs):
        params = {
            'use_label_encoder': False,
            'eval_metric': 'logloss',
            'tree_method': 'hist',
            'enable_categorical': True,
            'n_estimators': n_estimators,
            'early_stopping_rounds': early_stopping_rounds
        }
        params.update(kwargs)
        self.model = xgb.XGBClassifier(**params)
        self.best_params = None
        self.leakage_cols = [
            'home_ppg_l10', 'away_ppg_l10', 'home_blk_l10', 'away_blk_l10', 
            'home_stl_l10', 'away_stl_l10', 'home_fg_pct_l10', 'away_fg_pct_l10', 
            'home_fg3_pct_l10', 'away_fg3_pct_l10', 'ppg_diff', 'opp_ppg_diff'
        ]
        
    def getLeakageColumns(self):
        return self.leakage_cols
    
    def train(self, X_train, y_train, X_val=None, y_val=None, verbose=True):
        if X_val is not None and y_val is not None:
            # Train with validation set for early stopping
            self.model.fit(
                X_train, y_train,
                eval_set=[(X_train, y_train), (X_val, y_val)],
                verbose=verbose  # Shows eval metrics every round if True, or every N rounds if int
            )
            print(f"\nBest iteration: {self.model.best_iteration}")
            print(f"Best score: {self.model.best_score:.4f}")
        else:
            # Train without early stopping
            self.model.fit(X_train, y_train)
        
    def evaluate(self, X_val, y_val):
        y_pred = self.model.predict(X_val)
        y_pred_proba = self.model.predict_proba(X_val)[:, 1]
        
        accuracy = accuracy_score(y_val, y_pred)
        brier = brier_score_loss(y_val, y_pred_proba)
        logloss = log_loss(y_val, y_pred_proba)
        auc = roc_auc_score(y_val, y_pred_proba)
        
        return accuracy, brier, logloss, auc

    def predict(self, X_test):
        return self.model.predict(X_test)
    
    def predictProb(self, X_test):
        return self.model.predict_proba(X_test)
    
    def save(self, path):
        self.model.saveModel(path)
    
    def load(self, path):
        self.model.load_model(path)
    
    def tuneHyperparameters(self, X_train, y_train, X_val, y_val, n_trials=100, metric='logloss'):
        print(f"\nStarting hyperparameter tuning with {n_trials} trials...")
        print(f"Optimizing for: {metric}")
        
        def objective(trial):
            params = {
                'max_depth': trial.suggest_int('max_depth', 3, 10),
                'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.3, log=True),
                'subsample': trial.suggest_float('subsample', 0.6, 1.0),
                'colsample_bytree': trial.suggest_float('colsample_bytree', 0.6, 1.0),
                'min_child_weight': trial.suggest_int('min_child_weight', 1, 10),
                'gamma': trial.suggest_float('gamma', 0, 5),
                'reg_alpha': trial.suggest_float('reg_alpha', 0, 10),
                'reg_lambda': trial.suggest_float('reg_lambda', 0, 10),
                'n_estimators': 1000,
                'early_stopping_rounds': 50,
                'use_label_encoder': False,
                'eval_metric': 'logloss',
                'tree_method': 'hist',
                'enable_categorical': True,
                'random_state': 42
            }
            
            model = xgb.XGBClassifier(**params)
            model.fit(
                X_train, y_train,
                eval_set=[(X_val, y_val)],
                verbose=False
            )
            
            y_pred_proba = model.predict_proba(X_val)[:, 1]
            y_pred = model.predict(X_val)
            
            if metric == 'logloss':
                score = log_loss(y_val, y_pred_proba)
            elif metric == 'auc':
                score = -roc_auc_score(y_val, y_pred_proba)
            elif metric == 'accuracy':
                score = -accuracy_score(y_val, y_pred)
            elif metric == 'brier':
                score = brier_score_loss(y_val, y_pred_proba)
            else:
                raise ValueError(f"Unknown metric: {metric}")
            
            return score
        
        sampler = TPESampler(seed=42)
        study = optuna.create_study(
            direction='minimize',
            sampler=sampler,
            study_name='basketball_model_tuning'
        )
        
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        study.optimize(objective, n_trials=n_trials, show_progress_bar=True)
        
        self.best_params = study.best_params
        
        print(f"\nBest trial:")
        print(f"  Value ({metric}): {study.best_value:.4f}")
        print(f"\nBest hyperparameters:")
        for key, value in self.best_params.items():
            print(f"  {key}: {value}")
        
        return self.best_params
    
    def trainWithBestParams(self, X_train, y_train, X_val=None, y_val=None, verbose=True):
        if self.best_params is None:
            raise ValueError("No best parameters found. Run tuneHyperparameters() first.")
        
        print("\nTraining model with best hyperparameters...")
        
        params = self.best_params.copy()
        params.update({
            'use_label_encoder': False,
            'eval_metric': 'logloss',
            'tree_method': 'hist',
            'enable_categorical': True,
            'n_estimators': params.get('n_estimators', 1000),
            'early_stopping_rounds': params.get('early_stopping_rounds', 50),
            'random_state': 42
        })
        
        self.model = xgb.XGBClassifier(**params)
        
        if X_val is not None and y_val is not None:
            self.model.fit(
                X_train, y_train,
                eval_set=[(X_train, y_train), (X_val, y_val)],
                verbose=verbose
            )
            print(f"\nBest iteration: {self.model.best_iteration}")
            print(f"Best score: {self.model.best_score:.4f}")
        else:
            self.model.fit(X_train, y_train)
    
    def getBestParams(self):
        return self.best_params
    
    def plotDiagnostics(self, X_val, y_val, X_test, y_test, save_dir='./plots/basketball/h2h/'):
        Path(save_dir).mkdir(parents=True, exist_ok=True)
        
        # Get predictions
        val_proba = self.model.predict_proba(X_val)[:, 1]
        test_proba = self.model.predict_proba(X_test)[:, 1]
        
        # 1. Feature Importance Plot
        self.plotFeatureImportance(save_dir)
        
        # 2. ROC Curve Comparison
        self.plotRocCurves(y_val, val_proba, y_test, test_proba, save_dir)
        
        # 3. Calibration Plot (Reliability Diagram)
        self.plotCalibration(y_val, val_proba, y_test, test_proba, save_dir)
        
        # 4. Confidence vs Accuracy Plot
        self.plotConfidenceAccuracy(y_val, val_proba, y_test, test_proba, save_dir)
        
        print(f"\nAll diagnostic plots saved to: {save_dir}/")
    
    def plotFeatureImportance(self, save_dir):
        importance_df = pd.DataFrame({
            'feature': self.model.get_booster().feature_names,
            'importance': self.model.feature_importances_
        }).sort_values('importance', ascending=False)
        
        plt.figure(figsize=(10, 8))
        sns.barplot(data=importance_df, y='feature', x='importance', palette='viridis')
        plt.title(f'Top {len(importance_df)} Feature Importances', fontsize=14, fontweight='bold')
        plt.xlabel('Importance Score')
        plt.ylabel('Feature')
        plt.tight_layout()
        plt.savefig(f'{save_dir}/feature_importance.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    def printLowImportanceFeatures(self, threshold=0.01):
        importance_df = pd.DataFrame({
            'feature': self.model.get_booster().feature_names,
            'importance': self.model.feature_importances_
        }).sort_values('importance', ascending=True)
        
        low_importance = importance_df[importance_df['importance'] < threshold]
        
        print(f"\nFeatures with importance < {threshold}:")
        print(f"Total: {len(low_importance)} features\n")
        
        if len(low_importance) > 0:
            print(f"{'Feature':<40} {'Importance':>12}")
            print("-" * 52)
            for _, row in low_importance.iterrows():
                print(f"{row['feature']:<40} {row['importance']:>12.6f}")
            
            print("\n" + "="*52)
            print("Copy-paste ready list for removal:")
            print("="*52)
            feature_list = "[\n    '" + "',\n    '".join(low_importance['feature'].tolist()) + "'\n]"
            print(feature_list)
        else:
            print(f"No features found below threshold {threshold}")
        
        return low_importance['feature'].tolist()
    
    def plotRocCurves(self, y_val, val_proba, y_test, test_proba, save_dir):
        fpr_val, tpr_val, _ = roc_curve(y_val, val_proba)
        fpr_test, tpr_test, _ = roc_curve(y_test, test_proba)
        
        val_auc = roc_auc_score(y_val, val_proba)
        test_auc = roc_auc_score(y_test, test_proba)
        
        plt.figure(figsize=(8, 8))
        plt.plot(fpr_val, tpr_val, label=f'Validation (AUC = {val_auc:.3f})', linewidth=2)
        plt.plot(fpr_test, tpr_test, label=f'Test (AUC = {test_auc:.3f})', linewidth=2)
        plt.plot([0, 1], [0, 1], 'k--', label='Random Classifier', linewidth=1)
        plt.xlabel('False Positive Rate', fontsize=12)
        plt.ylabel('True Positive Rate', fontsize=12)
        plt.title('ROC Curves - Model Performance', fontsize=14, fontweight='bold')
        plt.legend(loc='lower right', fontsize=10)
        plt.grid(alpha=0.3)
        plt.tight_layout()
        plt.savefig(f'{save_dir}/roc_curves.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    def plotCalibration(self, y_val, val_proba, y_test, test_proba, save_dir):
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
        
        for ax, y_true, y_prob, title in [(ax1, y_val, val_proba, 'Validation'),
                                            (ax2, y_test, test_proba, 'Test')]:
            # Bin predictions
            bins = np.linspace(0, 1, 11)
            bin_centers = (bins[:-1] + bins[1:]) / 2
            bin_indices = np.digitize(y_prob, bins) - 1
            bin_indices = np.clip(bin_indices, 0, len(bin_centers) - 1)
            
            # Calculate actual win rate per bin
            bin_true = [y_true[bin_indices == i].mean() if (bin_indices == i).sum() > 0 else np.nan 
                       for i in range(len(bin_centers))]
            bin_counts = [(bin_indices == i).sum() for i in range(len(bin_centers))]
            
            # Plot
            ax.plot([0, 1], [0, 1], 'k--', label='Perfect Calibration', linewidth=2)
            ax.scatter(bin_centers, bin_true, s=[c*2 for c in bin_counts], alpha=0.6, label='Actual')
            ax.plot(bin_centers, bin_true, 'o-', linewidth=2, markersize=8)
            ax.set_xlabel('Predicted Probability', fontsize=11)
            ax.set_ylabel('Actual Win Rate', fontsize=11)
            ax.set_title(f'{title} Set Calibration', fontsize=12, fontweight='bold')
            ax.legend(fontsize=9)
            ax.grid(alpha=0.3)
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
        
        plt.tight_layout()
        plt.savefig(f'{save_dir}/calibration_plot.png', dpi=300, bbox_inches='tight')
        plt.close()

    def plotConfidenceAccuracy(self, y_val, val_proba, y_test, test_proba, save_dir):
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
        
        for ax, y_true, y_prob, title in [(ax1, y_val, val_proba, 'Validation'), (ax2, y_test, test_proba, 'Test')]:
            # Convert probabilities to confidence (distance from 0.5)
            confidence = np.abs(y_prob - 0.5) * 2  # Scale to 0-1
            predictions = (y_prob > 0.5).astype(int)
            correct = (predictions == y_true).astype(int)
            
            # Bin by confidence
            bins = np.linspace(0, 1, 11)
            bin_centers = (bins[:-1] + bins[1:]) / 2
            bin_indices = np.digitize(confidence, bins) - 1
            bin_indices = np.clip(bin_indices, 0, len(bin_centers) - 1)
            
            bin_accuracy = [correct[bin_indices == i].mean() if (bin_indices == i).sum() > 0 else np.nan
                           for i in range(len(bin_centers))]
            bin_counts = [(bin_indices == i).sum() for i in range(len(bin_centers))]
            
            # Plot
            ax.bar(bin_centers, bin_accuracy, width=0.08, alpha=0.7, color='steelblue', edgecolor='black')
            ax2_twin = ax.twinx()
            ax2_twin.plot(bin_centers, bin_counts, 'ro-', linewidth=2, markersize=6, label='Sample Count')
            ax2_twin.set_ylabel('Number of Predictions', fontsize=10, color='red')
            ax2_twin.tick_params(axis='y', labelcolor='red')
            
            ax.set_xlabel('Confidence Level', fontsize=11)
            ax.set_ylabel('Accuracy', fontsize=11)
            ax.set_title(f'{title} Set - Accuracy by Confidence', fontsize=12, fontweight='bold')
            ax.set_ylim(0, 1)
            ax.grid(alpha=0.3, axis='y')
            ax2_twin.legend(loc='upper left', fontsize=9)
        
        plt.tight_layout()
        plt.savefig(f'{save_dir}/confidence_accuracy.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    def printPredictionSummary(self, X_test, y_test, team_col='home_team'):
        proba = self.model.predict_proba(X_test)[:, 1]
        pred = self.model.predict(X_test)
        
        print("\n" + "="*60)
        print("PREDICTION SUMMARY")
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

    def analyzeCalibration(self, y_true, y_pred_proba):    
        bins = [0, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 1.0]
        
        for i in range(len(bins)-1):
            mask = (y_pred_proba >= bins[i]) & (y_pred_proba < bins[i+1])
            if mask.sum() > 0:
                actual_win_rate = y_true[mask].mean()
                predicted_avg = y_pred_proba[mask].mean()
                print(f"Predicted {bins[i]:.0%}-{bins[i+1]:.0%}: "
                    f"Avg pred={predicted_avg:.1%}, "
                    f"Actual={actual_win_rate:.1%}, "
                    f"n={mask.sum()}")

    def saveModel(self, path):
        self.model.save_model(path)

    def getModelType(self):
        return 'h2h'
        