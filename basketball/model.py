import xgboost as xgb
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score, confusion_matrix, roc_curve
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

class BasketballModel:
    def __init__(self, n_estimators=1000, early_stopping_rounds=50):
        self.model = xgb.XGBClassifier(
            use_label_encoder=False, 
            eval_metric='logloss',
            tree_method='hist',
            enable_categorical=True,
            n_estimators=n_estimators,
            early_stopping_rounds=early_stopping_rounds
        )
        
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
    
    def predict_proba(self, X_test):
        return self.model.predict_proba(X_test)
    
    def save(self, path):
        self.model.save_model(path)
    
    def load(self, path):
        self.model.load_model(path)
    
    def plot_diagnostics(self, X_val, y_val, X_test, y_test, save_dir='./plots'):
        Path(save_dir).mkdir(parents=True, exist_ok=True)
        
        # Get predictions
        val_proba = self.model.predict_proba(X_val)[:, 1]
        test_proba = self.model.predict_proba(X_test)[:, 1]
        val_pred = self.model.predict(X_val)
        test_pred = self.model.predict(X_test)
        
        # 1. Feature Importance Plot
        self._plot_feature_importance(save_dir)
        
        # 2. ROC Curve Comparison
        self._plot_roc_curves(y_val, val_proba, y_test, test_proba, save_dir)
        
        # 3. Calibration Plot (Reliability Diagram)
        self._plot_calibration(y_val, val_proba, y_test, test_proba, save_dir)
        
        print(f"\nAll diagnostic plots saved to: {save_dir}/")
    
    def _plot_feature_importance(self, save_dir):
        importance_df = pd.DataFrame({
            'feature': self.model.get_booster().feature_names,
            'importance': self.model.feature_importances_
        }).sort_values('importance', ascending=False).head(20)
        
        plt.figure(figsize=(10, 8))
        sns.barplot(data=importance_df, y='feature', x='importance', palette='viridis')
        plt.title('Top 20 Feature Importances', fontsize=14, fontweight='bold')
        plt.xlabel('Importance Score')
        plt.ylabel('Feature')
        plt.tight_layout()
        plt.savefig(f'{save_dir}/feature_importance.png', dpi=300, bbox_inches='tight')
        plt.close()
        print("✓ Feature importance plot saved")
    
    def _plot_roc_curves(self, y_val, val_proba, y_test, test_proba, save_dir):
        """Plot ROC curves for validation and test sets"""
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
    
    def _plot_calibration(self, y_val, val_proba, y_test, test_proba, save_dir):
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
    
    def print_prediction_summary(self, X_test, y_test, team_col='home_team'):
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

basketball_model = BasketballModel()

# Load all seasons data
load_data = pd.read_csv('././data/training_data/basketball/phase1/all_seasons_training_data.csv')

# Split by season FIRST: train (2015-16 to 2022-23), val (2023-24), test (2024-25)
train_seasons = ['2015-16', '2016-17', '2017-18', '2018-19', '2019-20', '2020-21', '2021-22', '2022-23']
val_season = '2023-24'
test_season = '2024-25'

train_data = load_data[load_data['season'].isin(train_seasons)]
val_data = load_data[load_data['season'] == val_season]
test_data = load_data[load_data['season'] == test_season]

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
print("\nFeature dtypes:")
print(X_train.dtypes)

# Train the model with early stopping
print("\n" + "="*60)
print("TRAINING MODEL")
print("="*60)
basketball_model.train(X_train, y_train, X_val, y_val, verbose=100)  # Show eval every 100 rounds

# Evaluate on validation set
val_accuracy, val_brier, val_logloss, val_auc = basketball_model.evaluate(X_val, y_val)
print(f"\nValidation Metrics (2023-24):")
print(f"Accuracy: {val_accuracy:.4f}")
print(f"Brier Score: {val_brier:.4f}")
print(f"Log Loss: {val_logloss:.4f}")
print(f"AUC-ROC: {val_auc:.4f}")

# Evaluate on test set
test_accuracy, test_brier, test_logloss, test_auc = basketball_model.evaluate(X_test, y_test)
print(f"\nTest Metrics (2024-25):")
print(f"Accuracy: {test_accuracy:.4f}")
print(f"Brier Score: {test_brier:.4f}")
print(f"Log Loss: {test_logloss:.4f}")
print(f"AUC-ROC: {test_auc:.4f}")

# Generate diagnostic plots
basketball_model.plot_diagnostics(X_val, y_val, X_test, y_test, save_dir='./plots/basketball')

# Print prediction summary
basketball_model.print_prediction_summary(X_test, y_test)

# basketball_model.save('././models/basketball_model.')