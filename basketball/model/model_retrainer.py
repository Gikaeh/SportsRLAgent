import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from sklearn.model_selection import train_test_split
from model.model_h2h import BasketballH2HModel
from model.model_spread import BasketballSpreadModel
from data_pipeline.prepare_data import NBATrainingDataPreparer
from data_pipeline.basketball_data import BasketballData
import json

class ModelRetrainer:
    def __init__(self, model_path='./models/basketball_h2h_model.json', data_dir='./data/basketball', metadata_path='./models/metadata/retraining_h2h_metadata.json'):
        self.model_path = Path(model_path)
        self.data_dir = Path(data_dir)
        self.plot_dir = Path('./plots/basketball')
        self.training_data_dir = Path('./data/training_data/basketball/phase1')
        self.preparer = NBATrainingDataPreparer(data_dir=str(data_dir))
        self.basketball_data = BasketballData()

        if model_path.split('_')[1] == 'h2h':
            self.model = BasketballH2HModel()
        elif model_path.split('_')[1] == 'spread':
            self.model = BasketballSpreadModel()

        if self.model_path.exists():
            self.model.load(str(self.model_path))
            print(f"Loaded existing model from {self.model_path}")
        else:
            print(f"No existing model found at {self.model_path}")
        
        self.retrain_config = {
            'min_new_games': 50,
            'retrain_frequency_days': 7,
            'test_split': 0.2,
            'validation_split': 0.5,
            'keep_recent_seasons': None,
        }
        
        self.metadata_path = Path(metadata_path)
        self.metadata = self.loadMetadata()
    
    def loadMetadata(self):
        if self.metadata_path.exists():
            with open(self.metadata_path, 'r') as f:
                return json.load(f)
        else:
            return {
                'last_retrain_date': None,
                'total_games_trained': 0,
                'model_version': 1,
                'retrain_history': []
            }
    
    def saveMetadata(self):
        with open(self.metadata_path, 'w') as f:
            json.dump(self.metadata, f, indent=2)
    
    def checkIfRetrainNeeded(self):
        if self.metadata['last_retrain_date'] is None:
            return True, "Initial training required"
        
        last_retrain = datetime.fromisoformat(self.metadata['last_retrain_date'])
        days_since_retrain = (datetime.now() - last_retrain).days
        
        if days_since_retrain >= self.retrain_config['retrain_frequency_days']:
            return True, f"Scheduled retrain ({days_since_retrain} days since last retrain)"
        
        current_game_count = self.countAvailableGames()
        new_games = current_game_count - self.metadata['total_games_trained']
        
        if new_games >= self.retrain_config['min_new_games']:
            return True, f"{new_games} new games available (threshold: {self.retrain_config['min_new_games']})"
        
        return False, f"No retrain needed (only {new_games} new games, {days_since_retrain} days since last retrain)"
    
    def countAvailableGames(self):
        master_file = self.training_data_dir / 'all_seasons_training_data.csv'
        season_count = self.retrain_config['keep_recent_seasons']
        self.basketball_data.getAllSeasonData()
        self.preparer.prepareAllSeasons()

        if season_count is None:
            df = pd.read_csv(master_file)
            return len(df)

        if master_file.exists():
            df = pd.read_csv(master_file)
            unique_seasons = df['season'].unique()
            recent_seasons = unique_seasons[-season_count:]
            return len(df[df['season'].isin(recent_seasons)])
        
        return 0
    
    def prepareTrainingData(self, seasons=None):
        print("\n" + "="*60)
        print("PREPARING TRAINING DATA")
        print("="*60)
        
        training_data = self.preparer.prepareAllSeasons()
        print('hello')
        
        if training_data is None or training_data.empty:
            print("No training data available")
            return None
        
        if seasons is not None:
            training_data = training_data[training_data['season'].isin(seasons)]

        elif self.retrain_config['keep_recent_seasons'] is not None:
            unique_seasons = sorted(training_data['season'].unique())
            recent_seasons = unique_seasons[-self.retrain_config['keep_recent_seasons']:]
            training_data = training_data[training_data['season'].isin(recent_seasons)]
            print(f"Using recent seasons: {', '.join(recent_seasons)}")
        
        print(f"Total games in training data: {len(training_data)}")
        
        return training_data
    
    def retrainModel(self, training_data=None, tune_hyperparameters=True, n_trials=100):
        print("\n" + "="*80)
        print("MODEL RETRAINING")
        print("="*80)
        
        if training_data is None:
            training_data = self.prepareTrainingData()
        
        if training_data is None or training_data.empty:
            return {'success': False, 'error': 'No training data available'}
        
        train_data, test_data = train_test_split(training_data, test_size=self.retrain_config['test_split'], random_state=42)
        val_data, test_data = train_test_split(test_data, test_size=self.retrain_config['validation_split'], random_state=42)
        
        if self.model.getModelType() == 'h2h':
            leakage_cols = [
                'game_id', 'date', 'home_score', 'away_score', 
                'season', 'home_team', 'away_team', 'point_diff', 
                'home_ppg_l10', 'away_ppg_l10', 'home_blk_l10', 'away_blk_l10', 
                'home_stl_l10', 'away_stl_l10', 'home_fg_pct_l10', 'away_fg_pct_l10', 
                'home_fg3_pct_l10', 'away_fg3_pct_l10'
                ]

            train_data = train_data.drop(columns=[col for col in leakage_cols if col in train_data.columns])
            val_data = val_data.drop(columns=[col for col in leakage_cols if col in val_data.columns])
            test_data = test_data.drop(columns=[col for col in leakage_cols if col in test_data.columns])
            
            X_train, y_train = train_data.drop('home_won', axis=1), train_data['home_won']
            X_val, y_val = val_data.drop('home_won', axis=1), val_data['home_won']
            X_test, y_test = test_data.drop('home_won', axis=1), test_data['home_won']
        elif self.model.getModelType() == 'spread':
            leakage_cols = [
                'game_id', 'date', 'home_score', 'away_score', 
                'season', 'home_team', 'away_team', 'home_won',
                'home_blk_l10', 'away_blk_l10', 'home_stl_l10', 'away_stl_l10', 
                'home_fg_pct_l10', 'away_fg_pct_l10', 'home_fg3_pct_l10', 'away_fg3_pct_l10'
                ]

            train_data = train_data.drop(columns=[col for col in leakage_cols if col in train_data.columns])
            val_data = val_data.drop(columns=[col for col in leakage_cols if col in val_data.columns])
            test_data = test_data.drop(columns=[col for col in leakage_cols if col in test_data.columns])
            
            X_train, y_train = train_data.drop('home_won', axis=1), train_data['home_won']
            X_val, y_val = val_data.drop('home_won', axis=1), val_data['home_won']
            X_test, y_test = test_data.drop('home_won', axis=1), test_data['home_won']
        
        
        
        print(f"\nTraining set: {len(X_train)} games")
        print(f"Test set: {len(X_test)} games")
        
        if self.model.getModelType() == 'h2h':
            self.model = BasketballH2HModel()
        elif self.model.getModelType() == 'spread':
            self.model = BasketballSpreadModel()
        
        if tune_hyperparameters:
            print(f"\n{'='*60}")
            print("HYPERPARAMETER TUNING")
            print(f"{'='*60}")
            best_params = self.model.tuneHyperparameters(X_train, y_train, X_val, y_val, n_trials=n_trials)
            self.model.trainWithBestParams(X_train, y_train, X_val, y_val, verbose=50)
            self.model.analyzeCalibration(y_val, self.model.predictProb(X_val)[:, 1])
        else:
            print("\nTraining with existing hyperparameters...")
            self.model.train(X_train, y_train, X_val, y_val, verbose=50)
            self.model.analyzeCalibration(y_val, self.model.predictProb(X_val)[:, 1])
        
        val_accuracy, val_brier, val_logloss, val_auc = self.model.evaluate(X_val, y_val)
        test_accuracy, test_brier, test_logloss, test_auc = self.model.evaluate(X_test, y_test)
        
        print(f"\n{'='*60}")
        print("RETRAINING RESULTS")
        print(f"{'='*60}")
        print(f"Validation Accuracy: {val_accuracy:.4f}")
        print(f"Validation Brier Score: {val_brier:.4f}")
        print(f"Validation Log Loss: {val_logloss:.4f}")
        print(f"Validation AUC-ROC: {val_auc:.4f}")
        print(f"Test Accuracy: {test_accuracy:.4f}")
        print(f"Test Brier Score: {test_brier:.4f}")
        print(f"Test Log Loss: {test_logloss:.4f}")
        print(f"Test AUC-ROC: {test_auc:.4f}")
        
        self.model.saveModel(str(self.model_path))
        print(f"\nModel saved to {self.model_path}")

        self.model.plotDiagnostics(X_val, y_val, X_test, y_test, save_dir=self.plot_dir)
        
        self.metadata['last_retrain_date'] = datetime.now().isoformat()
        self.metadata['total_games_trained'] = len(training_data)
        self.metadata['model_version'] += 1
        self.metadata['retrain_history'].append({
            'date': datetime.now().isoformat(),
            'games_trained': len(training_data),
            'val_accuracy': val_accuracy,
            'val_brier_score': val_brier,
            'val_log_loss': val_logloss,
            'val_auc_roc': val_auc,
            'test_accuracy': test_accuracy,
            'test_brier_score': test_brier,
            'test_log_loss': test_logloss,
            'test_auc_roc': test_auc,
            'hyperparameter_tuning': tune_hyperparameters
        })
        self.saveMetadata()
        
        return {
            'success': True,
            'val_accuracy': val_accuracy,
            'val_brier_score': val_brier,
            'val_log_loss': val_logloss,
            'val_auc_roc': val_auc,
            'test_accuracy': test_accuracy,
            'test_brier_score': test_brier,
            'test_log_loss': test_logloss,
            'test_auc_roc': test_auc,
            'games_trained': len(training_data),
            'model_version': self.metadata['model_version']
        }
    
    def autoRetrainIfNeeded(self, force=False):
        if force:
            print("FORCED RETRAINING")
            return self.retrainModel()
        
        should_retrain, reason = self.checkIfRetrainNeeded()
        
        print("\n" + "="*60)
        print("RETRAINING CHECK")
        print("="*60)
        print(f"Should retrain: {should_retrain}")
        print(f"Reason: {reason}")
        
        if should_retrain:
            return self.retrainModel()
        else:
            return {'success': False, 'reason': reason, 'skipped': True}
    
    def getRetrainingStatus(self):
        print("\n" + "="*60)
        print("MODEL RETRAINING STATUS")
        print("="*60)
        print(f"Model Version: {self.metadata['model_version']}")
        print(f"Last Retrain: {self.metadata['last_retrain_date']}")
        print(f"Total Games Trained: {self.metadata['total_games_trained']}")
        print(f"\nRetrain History ({len(self.metadata['retrain_history'])} retrains):")
        
        for i, entry in enumerate(self.metadata['retrain_history'][-5:], 1):
            print(f"\n  #{i} - {entry['date']}")
            print(f"     Games: {entry['games_trained']}")
            print(f"     Validation Accuracy: {entry['val_accuracy']:.4f}")
            print(f"     Validation Log Loss: {entry['val_log_loss']:.4f}")
            print(f"     Test Accuracy: {entry['test_accuracy']:.4f}")
            print(f"     Test Log Loss: {entry['test_log_loss']:.4f}")
        
        return self.metadata