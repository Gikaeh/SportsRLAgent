import xgboost as xgb
from sklearn.inspection import permutation_importance
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
import optuna
from optuna.samplers import TPESampler

class BasketballTotalModel:
    def __init__(self, n_estimators=1000, early_stopping_rounds=50, **kwargs):
        params = {
            'objective': 'reg:absoluteerror',
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
            'game_id', 'date', 'home_score', 'away_score', 'point_diff',
            'season', 'home_team', 'away_team', 'home_won',
        ]
        self.low_importance_cols = [
            'away_blk_l10', 'away_fg_pct_l10', 'away_opp_avg_win_pct_l10', 'away_plus_minus_l10', 'away_rest_days', 
            'away_stl_l10', 'away_top3_avg_blk', 'away_top3_avg_stl', 'away_top3_avg_tov', 'away_top5_avg_stl', 
            'away_top5_avg_tov', 'away_top6_avg_apg', 'away_top6_avg_blk', 'away_top6_avg_stl', 'away_tov_l10', 
            'home_blk_l10', 'home_stl_l10', 'home_top3_avg_ppg', 'home_top3_avg_stl', 'home_top5_avg_tov', 
            'home_top6_avg_apg', 'home_top6_avg_stl', 'home_top6_avg_tov', 'opp_avg_win_pct_diff', 'rest_days_diff', 
            'stl_l10_diff', 'tov_l10_diff', 'apg_l10_diff', 'away_top5_avg_blk', 'away_wins_l10', 
            'blk_l10_diff', 'home_opp_avg_win_pct_l10', 'home_plus_minus_l10', 'home_top5_avg_stl', 'home_top6_avg_rpg', 
            'home_tov_l10', 'is_back_to_back_away', 'ppg_diff', 'total_l10_diff', 'away_top3_avg_rpg',
            'plus_minus_diff', 'away_top3_avg_apg', 'away_top5_avg_rpg', 'home_top3_avg_apg', 'home_top3_avg_blk', 
            'home_top5_avg_blk', 'home_top6_avg_mpg', 'reb_l10_diff'
        ]

    def getLeakageColumns(self):
        return self.leakage_cols + self.low_importance_cols
        
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
        
    def evaluate(self, X_val, y_val, X_train=None, save_dir='./plots/basketball/total/'):
        Path(save_dir).mkdir(parents=True, exist_ok=True)

        y_pred = self.model.predict(X_val)
        
        mae = mean_absolute_error(y_val, y_pred)
        rmse = np.sqrt(mean_squared_error(y_val, y_pred))
        r2 = r2_score(y_val, y_pred)
        
        # Calculate accuracy within different point thresholds
        within_3 = np.mean(np.abs(y_val - y_pred) <= 3)
        within_5 = np.mean(np.abs(y_val - y_pred) <= 5)
        within_10 = np.mean(np.abs(y_val - y_pred) <= 10)
        
        print(f"\nRegression Metrics:")
        print(f"  MAE: {mae:.3f} points")
        print(f"  RMSE: {rmse:.3f} points")
        print(f"  R²: {r2:.3f}")
        print(f"\nPrediction Accuracy:")
        print(f"  Within 3 pts: {within_3:.1%}")
        print(f"  Within 5 pts: {within_5:.1%}")
        print(f"  Within 10 pts: {within_10:.1%}")

        if X_train is not None:
            _, removals = self.analyzeFeatureImportance(X_train, X_val, y_val, save_dir)
            return mae, rmse, r2, within_3, within_5, within_10, removals
        
        return mae, rmse, r2, within_3, within_5, within_10

    def predict(self, X_test):
        return self.model.predict(X_test)
    
    def predictOverUnder(self, X_test, total_line):
        predicted_total = self.model.predict(X_test)
        return predicted_total > total_line
    
    def evaluateOverUnderAccuracy(self, X_test, y_test, total_line):
        predicted_total = self.model.predict(X_test)
        actual_over = y_test > total_line
        predicted_over = predicted_total > total_line
        accuracy = np.mean(actual_over == predicted_over)
        
        print(f"\nOver/Under Analysis (line = {total_line}):")
        print(f"  Prediction Accuracy: {accuracy:.1%}")
        print(f"  Actual overs: {actual_over.sum()}/{len(actual_over)}")
        print(f"  Predicted overs: {predicted_over.sum()}/{len(predicted_over)}")
        
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
                'objective': 'reg:absoluteerror',
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
            study_name='basketball_total_tuning'
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
            'objective': 'reg:absoluteerror',
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
    
    def plotDiagnostics(self, X_val, y_val, X_test, y_test, save_dir='././plots/basketball/total/'):
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
        importance_df = pd.DataFrame({
            'feature': self.model.get_booster().feature_names,
            'importance': self.model.feature_importances_
        }).sort_values('importance', ascending=False)
        
        plt.figure(figsize=(10, 8))
        sns.barplot(data=importance_df, y='feature', x='importance', palette='viridis')
        plt.title(f'{len(importance_df)} Feature Importances - Total Points', fontsize=14, fontweight='bold')
        plt.xlabel('Importance Score')
        plt.ylabel('Feature')
        plt.tight_layout()
        plt.savefig(f'{save_dir}/feature_importance_total.png', dpi=300, bbox_inches='tight')
        plt.close()

    def analyzeFeatureImportance(self, X_train, X_val, y_val, save_dir='././plots/basketball/spread/', n_repeats=10):
        scoring = 'neg_mean_absolute_error'
        perm_importance = permutation_importance(
            self.model, X_val, y_val, n_repeats=n_repeats, scoring=scoring, random_state=42
        )

        importance_df = pd.DataFrame({
            'feature': X_val.columns,
            'perm_importance': perm_importance.importances_mean,
            'perm_std': perm_importance.importances_std,
            'xgb_importance': self.model.feature_importances_
        }).sort_values('perm_importance', ascending=False)

        negative_features = importance_df[importance_df['perm_importance'] < 0].copy()

        if len(negative_features) > 0:
            print(f"Total harmful features: {len(negative_features)}\n")
            print(f"{'Feature':<40} {'Perm Imp':>12} {'XGB Imp':>12}")
            print("-" * 65)
            for _, row in negative_features.iterrows():
                print(f"{row['feature']:<40} {row['perm_importance']:>12.6f} {row['xgb_importance']:>12.6f}")
        else:
            print("No harmful features found!")

        low_importance = importance_df[
            (importance_df['perm_importance'] >= 0) & (importance_df['perm_importance'] < 0.001)
        ].copy()

        if len(low_importance) > 0:
            print(f"\nTotal near-zero importance features: {len(low_importance)}\n")
            print(f"{'Feature':<40} {'Perm Imp':>12} {'XGB Imp':>12}")
            print("-" * 65)
            for _, row in low_importance.iterrows():
                print(f"{row['feature']:<40} {row['perm_importance']:>12.6f} {row['xgb_importance']:>12.6f}")

        corr_matrix = X_train.corr().abs()
        features_to_remove = []
        removal_reasons = []

        for feat in importance_df[importance_df['perm_importance'] < 0.001]['feature']:
            correlated_features = corr_matrix[feat][corr_matrix[feat] > 0.8].index.tolist()

            for corr_feat in correlated_features:
                if corr_feat != feat:
                    corr_row = importance_df[importance_df['feature'] == corr_feat]
                    feat_row = importance_df[importance_df['feature'] == feat]
                    if len(corr_row) == 0 or len(feat_row) == 0:
                        continue
                    if corr_row['perm_importance'].values[0] > 0.001:
                        features_to_remove.append(feat)
                        removal_reasons.append({
                            'feature': feat,
                            'perm_imp': feat_row['perm_importance'].values[0],
                            'correlated_with': corr_feat,
                            'corr_feat_imp': corr_row['perm_importance'].values[0],
                            'correlation': corr_matrix.loc[feat, corr_feat]
                        })
                        break

        features_to_remove = sorted(set(features_to_remove))

        if removal_reasons:
            print(f"\nFound {len(features_to_remove)} redundant low-importance features:\n")
            print(f"{'Feature':<30} {'Perm Imp':>10} {'Correlated With':<30} {'Corr':>6} {'Better Imp':>10}")
            print("-" * 100)
            for reason in removal_reasons:
                print(f"{reason['feature']:<30} {reason['perm_imp']:>10.6f} "
                        f"{reason['correlated_with']:<30} {reason['correlation']:>6.3f} "
                        f"{reason['corr_feat_imp']:>10.6f}")

        all_removals = sorted(set(list(negative_features['feature']) + features_to_remove))
        print(f"\nTotal candidate removals: {len(all_removals)}")
        print(f"  - Harmful (negative importance): {len(negative_features)}")
        print(f"  - Near-zero + correlated with a useful feature: {len(features_to_remove)}")

        if save_dir is not None:
            Path(save_dir).mkdir(parents=True, exist_ok=True)
            importance_df.to_csv(f'{save_dir}/permutation_importance.csv', index=False)

        return importance_df, all_removals
    
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
            
            ax.set_xlabel('Actual Total Points', fontsize=11)
            ax.set_ylabel('Predicted Total Points', fontsize=11)
            ax.set_title(f'{title} Set\nMAE: {mae:.2f}, R²: {r2:.3f}', 
                        fontsize=12, fontweight='bold')
            ax.legend()
            ax.grid(alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(f'{save_dir}/predicted_vs_actual_total.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    def plotResiduals(self, y_val, val_pred, y_test, test_pred, save_dir):
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        
        for idx, (y_true, y_pred, title) in enumerate([(y_val, val_pred, 'Validation'),
                                                         (y_test, test_pred, 'Test')]):
            residuals = y_true - y_pred
            
            # Residual plot
            axes[idx, 0].scatter(y_pred, residuals, alpha=0.5, s=20)
            axes[idx, 0].axhline(y=0, color='r', linestyle='--', lw=2)
            axes[idx, 0].set_xlabel('Predicted Total Points')
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
        plt.savefig(f'{save_dir}/residuals_total.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    def plotErrorByPredictedRange(self, y_val, val_pred, y_test, test_pred, save_dir):
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
        
        for ax, y_true, y_pred, title in [(ax1, y_val, val_pred, 'Validation'),
                                            (ax2, y_test, test_pred, 'Test')]:
            # Bin predictions by total points ranges
            bins = [0, 200, 210, 220, 230, 240, 250, 300]
            bin_labels = ['<200', '200-210', '210-220', '220-230', 
                         '230-240', '240-250', '>250']
            
            errors = np.abs(y_true - y_pred)
            pred_bins = pd.cut(y_pred, bins=bins, labels=bin_labels)
            
            bin_mae = [errors[pred_bins == label].mean() 
                      for label in bin_labels]
            bin_counts = [np.sum(pred_bins == label) 
                         for label in bin_labels]
            
            x_pos = np.arange(len(bin_labels))
            ax.bar(x_pos, bin_mae, alpha=0.7, edgecolor='black')
            ax.set_xlabel('Predicted Total Points Range')
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
        plt.savefig(f'{save_dir}/error_by_range_total.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    def printPredictionSummary(self, X_test, y_test):
        predictions = self.model.predict(X_test)
        
        print("\n" + "="*60)
        print("TOTAL POINTS PREDICTION SUMMARY")
        print("="*60)
        
        # Overall stats
        print(f"\nTotal Predictions: {len(predictions)}")
        
        # Prediction ranges
        print(f"\nPrediction Statistics:")
        print(f"  Mean Predicted Total: {predictions.mean():.2f} points")
        print(f"  Std Dev: {predictions.std():.2f} points")
        print(f"  Min: {predictions.min():.2f} points")
        print(f"  Max: {predictions.max():.2f} points")
        
        print(f"\nActual Statistics:")
        print(f"  Mean Actual Total: {y_test.mean():.2f} points")
        print(f"  Std Dev: {y_test.std():.2f} points")
        print(f"  Min: {y_test.min():.2f} points")
        print(f"  Max: {y_test.max():.2f} points")
        
        # Error analysis
        errors = np.abs(y_test - predictions)
        print(f"\nError Statistics:")
        print(f"  Mean Absolute Error: {errors.mean():.2f} points")
        print(f"  Median Error: {np.median(errors):.2f} points")
        
        # Common total lines
        print(f"\nOver/Under Accuracy at Common Lines:")
        for total_line in [210.5, 215.5, 220.5, 225.5, 230.5, 235.5]:
            accuracy = self.evaluateOverUnderAccuracy(X_test, y_test, total_line)
        
        print("="*60)
    
    def saveModel(self, path):
        self.model.save_model(path)

    def getModelType(self):
        return 'total'