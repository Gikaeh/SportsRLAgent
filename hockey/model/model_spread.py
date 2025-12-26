import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
import optuna
from optuna.samplers import TPESampler

class HockeySpreadModel:
    def __init__(self, n_estimators=1000, early_stopping_rounds=50, **kwargs):
        params = {
            'objective': 'reg:squarederror',
            'eval_metric': 'mae',
            'tree_method': 'hist',
            'enable_categorical': True,
            'n_estimators': n_estimators,
            'early_stopping_rounds': early_stopping_rounds
        }
        params.update(kwargs)
        self.model = xgb.XGBRegressor(**params)
        self.best_params = None
        self.leakage_cols = [
            # 'home_blk_l10', 'away_blk_l10', 'home_stl_l10', 'away_stl_l10', 
            # 'home_fg_pct_l10', 'away_fg_pct_l10', 'home_fg3_pct_l10', 'away_fg3_pct_l10'
        ]
        
    def getLeakageColumns(self):
        return self.leakage_cols

    def train(self, X_train, y_train, X_val=None, y_val=None, verbose=True):
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
        
    def evaluate(self, X_val, y_val):
        y_pred = self.model.predict(X_val)
        
        mae = mean_absolute_error(y_val, y_pred)
        rmse = np.sqrt(mean_squared_error(y_val, y_pred))
        r2 = r2_score(y_val, y_pred)
        
        within_3 = np.mean(np.abs(y_val - y_pred) <= 3)
        within_5 = np.mean(np.abs(y_val - y_pred) <= 5)
        within_7 = np.mean(np.abs(y_val - y_pred) <= 7)
        
        print(f"\nRegression Metrics:")
        print(f"  MAE: {mae:.3f} points")
        print(f"  RMSE: {rmse:.3f} points")
        print(f"  R²: {r2:.3f}")
        print(f"\nPrediction Accuracy:")
        print(f"  Within 3 pts: {within_3:.1%}")
        print(f"  Within 5 pts: {within_5:.1%}")
        print(f"  Within 7 pts: {within_7:.1%}")
        
        return mae, rmse, r2, within_3, within_5, within_7

    def predict(self, X_test):
        return self.model.predict(X_test)
    
    def predictSpreadCoverage(self, X_test, spread):
        predicted_margin = self.model.predict(X_test)
        return predicted_margin > spread
    
    def evaluateSpreadAccuracy(self, X_test, y_test, spread):
        predicted_margin = self.model.predict(X_test)
        actual_cover = y_test > spread
        predicted_cover = predicted_margin > spread
        accuracy = np.mean(actual_cover == predicted_cover)
        
        print(f"\nSpread Coverage Analysis (spread = {spread}):")
        print(f"  Prediction Accuracy: {accuracy:.1%}")
        print(f"  Home covers actual: {actual_cover.sum()}/{len(actual_cover)}")
        print(f"  Home covers predicted: {predicted_cover.sum()}/{len(predicted_cover)}")
        
        return accuracy
    
    def save(self, path):
        self.model.save_model(path)
    
    def load(self, path):
        self.model.load_model(path)
    
    def tuneHyperparameters(self, X_train, y_train, X_val, y_val, n_trials=100, metric='mae'):
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
                'objective': 'reg:squarederror',
                'eval_metric': 'mae',
                'tree_method': 'hist',
                'enable_categorical': True,
                'random_state': 42
            }
            
            model = xgb.XGBRegressor(**params)
            model.fit(
                X_train, y_train,
                eval_set=[(X_val, y_val)],
                verbose=False
            )
            
            y_pred = model.predict(X_val)
            
            if metric == 'mae':
                score = mean_absolute_error(y_val, y_pred)
            elif metric == 'rmse':
                score = np.sqrt(mean_squared_error(y_val, y_pred))
            elif metric == 'r2':
                score = -r2_score(y_val, y_pred) 
            else:
                raise ValueError(f"Unknown metric: {metric}")
            
            return score
        
        sampler = TPESampler(seed=42)
        study = optuna.create_study(
            direction='minimize',
            sampler=sampler,
            study_name='basketball_spread_tuning'
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
            'objective': 'reg:squarederror',
            'eval_metric': 'mae',
            'tree_method': 'hist',
            'enable_categorical': True,
            'n_estimators': params.get('n_estimators', 1000),
            'early_stopping_rounds': params.get('early_stopping_rounds', 50),
            'random_state': 42
        })
        
        self.model = xgb.XGBRegressor(**params)
        
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
    
    def plotDiagnostics(self, X_val, y_val, X_test, y_test, save_dir='././plots/hockey/spread/'):
        Path(save_dir).mkdir(parents=True, exist_ok=True)
        
        val_pred = self.model.predict(X_val)
        test_pred = self.model.predict(X_test)
        
        # 1. Feature Importance Plot
        self.plotFeatureImportance(save_dir)
        
        # 2. Predicted vs Actual
        self.plotPredictedVsActual(y_val, val_pred, y_test, test_pred, save_dir)
        
        # 3. Residual Distribution
        self.plotResiduals(y_val, val_pred, y_test, test_pred, save_dir)
        
        # 4. Error Distribution by Range
        self.plotErrorByPredictedRange(y_val, val_pred, y_test, test_pred, save_dir)
        
        print(f"\nAll diagnostic plots saved to: {save_dir}/")
    
    def plotFeatureImportance(self, save_dir):
        importance_df = pd.DataFrame({'feature': self.model.get_booster().feature_names, 'importance': self.model.feature_importances_}).sort_values('importance', ascending=False)
        
        plt.figure(figsize=(10, 8))
        sns.barplot(data=importance_df, y='feature', x='importance', palette='viridis')
        plt.title(f'{len(importance_df)} Feature Importances', fontsize=14, fontweight='bold')
        plt.xlabel('Importance Score')
        plt.ylabel('Feature')
        plt.tight_layout()
        plt.savefig(f'{save_dir}/feature_importance.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    def printLowImportanceFeatures(self, threshold=0.01):
        importance_df = pd.DataFrame({'feature': self.model.get_booster().feature_names, 'importance': self.model.feature_importances_}).sort_values('importance', ascending=True)
        
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
    
    def plotPredictedVsActual(self, y_val, val_pred, y_test, test_pred, save_dir):
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
        
        for ax, y_true, y_pred, title in [(ax1, y_val, val_pred, 'Validation'),
                                            (ax2, y_test, test_pred, 'Test')]:
            ax.scatter(y_true, y_pred, alpha=0.5, s=20)
            ax.plot([y_true.min(), y_true.max()], 
                   [y_true.min(), y_true.max()], 
                   'r--', lw=2, label='Perfect Prediction')
            
            mae = mean_absolute_error(y_true, y_pred)
            r2 = r2_score(y_true, y_pred)
            
            ax.set_xlabel('Actual Point Differential', fontsize=11)
            ax.set_ylabel('Predicted Point Differential', fontsize=11)
            ax.set_title(f'{title} Set\nMAE: {mae:.2f}, R²: {r2:.3f}', 
                        fontsize=12, fontweight='bold')
            ax.legend()
            ax.grid(alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(f'{save_dir}/predicted_vs_actual.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    def plotResiduals(self, y_val, val_pred, y_test, test_pred, save_dir):
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        
        for idx, (y_true, y_pred, title) in enumerate([(y_val, val_pred, 'Validation'),
                                                         (y_test, test_pred, 'Test')]):
            residuals = y_true - y_pred
            
            # Residual plot
            axes[idx, 0].scatter(y_pred, residuals, alpha=0.5, s=20)
            axes[idx, 0].axhline(y=0, color='r', linestyle='--', lw=2)
            axes[idx, 0].set_xlabel('Predicted Point Differential')
            axes[idx, 0].set_ylabel('Residuals')
            axes[idx, 0].set_title(f'{title} Set - Residual Plot')
            axes[idx, 0].grid(alpha=0.3)
            
            # Residual distribution
            axes[idx, 1].hist(residuals, bins=30, edgecolor='black', alpha=0.7)
            axes[idx, 1].axvline(x=0, color='r', linestyle='--', lw=2)
            axes[idx, 1].set_xlabel('Residuals (Actual - Predicted)')
            axes[idx, 1].set_ylabel('Frequency')
            axes[idx, 1].set_title(f'{title} Set - Residual Distribution\nMean: {residuals.mean():.2f}, Std: {residuals.std():.2f}')
            axes[idx, 1].grid(alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(f'{save_dir}/residuals.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    def plotErrorByPredictedRange(self, y_val, val_pred, y_test, test_pred, save_dir):
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
        
        for ax, y_true, y_pred, title in [(ax1, y_val, val_pred, 'Validation'),
                                            (ax2, y_test, test_pred, 'Test')]:
            # Bin predictions
            bins = [-30, -15, -10, -5, 0, 5, 10, 15, 30]
            bin_labels = ['<-15', '-15 to -10', '-10 to -5', '-5 to 0', 
                         '0 to 5', '5 to 10', '10 to 15', '>15']
            
            errors = np.abs(y_true - y_pred)
            pred_bins = pd.cut(y_pred, bins=bins, labels=bin_labels)
            
            bin_mae = [errors[pred_bins == label].mean() 
                      for label in bin_labels]
            bin_counts = [np.sum(pred_bins == label) 
                         for label in bin_labels]
            
            x_pos = np.arange(len(bin_labels))
            ax.bar(x_pos, bin_mae, alpha=0.7, edgecolor='black')
            ax.set_xlabel('Predicted Point Differential Range')
            ax.set_ylabel('Mean Absolute Error')
            ax.set_title(f'{title} Set - MAE by Prediction Range')
            ax.set_xticks(x_pos)
            ax.set_xticklabels(bin_labels, rotation=45, ha='right')
            ax.grid(alpha=0.3, axis='y')
            
            # Add count labels
            for i, (mae, count) in enumerate(zip(bin_mae, bin_counts)):
                if not np.isnan(mae):
                    ax.text(i, mae, f'n={count}', ha='center', va='bottom', fontsize=8)
        
        plt.tight_layout()
        plt.savefig(f'{save_dir}/error_by_range.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    def printPredictionSummary(self, X_test, y_test):
        predictions = self.model.predict(X_test)
        
        print("\n" + "="*60)
        print("SPREAD PREDICTION SUMMARY")
        print("="*60)
        
        # Overall stats
        print(f"\nTotal Predictions: {len(predictions)}")
        print(f"Predicted Home Favored: {(predictions > 0).sum()} ({(predictions > 0).sum()/len(predictions)*100:.1f}%)")
        print(f"Predicted Away Favored: {(predictions < 0).sum()} ({(predictions < 0).sum()/len(predictions)*100:.1f}%)")
        print(f"Actual Home Wins: {(y_test > 0).sum()} ({(y_test > 0).sum()/len(y_test)*100:.1f}%)")
        
        # Prediction ranges
        print(f"\nPrediction Statistics:")
        print(f"  Mean Prediction: {predictions.mean():.2f} points")
        print(f"  Std Dev: {predictions.std():.2f} points")
        print(f"  Min: {predictions.min():.2f} points")
        print(f"  Max: {predictions.max():.2f} points")
        
        # Error analysis
        errors = np.abs(y_test - predictions)
        print(f"\nError Statistics:")
        print(f"  Mean Absolute Error: {errors.mean():.2f} points")
        print(f"  Median Error: {np.median(errors):.2f} points")
        
        # Common spread scenarios
        for spread in [-1.5, 1.5]:
            accuracy = self.evaluateSpreadAccuracy(X_test, y_test, spread)
        
        print("="*60)
    
    def saveModel(self, path):
        self.model.save_model(path)

    def getModelType(self):
        return 'spread'