from sklearn.model_selection import train_test_split
import xgboost as xgb
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score
import pandas as pd
import numpy as np

class BasketballModel:
    def __init__(self):
        self.model = xgb.XGBClassifier(
            use_label_encoder=False, 
            eval_metric='logloss',
            tree_method='hist',
            enable_categorical=True
        )
        
    def train(self, X_train, y_train):
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

basketball_model = BasketballModel()

# Load all seasons data
load_data = pd.read_csv('././data/training_data/basketball/phase1/all_seasons_training_data.csv')

# Drop leakage columns (post-game data and identifiers)
leakage_cols = ['game_id', 'date', 'home_score', 'away_score']
load_data = load_data.drop(columns=[col for col in leakage_cols if col in load_data.columns])

# Split by season: train (2015-16 to 2022-23), val (2023-24), test (2024-25)
train_seasons = ['2015-16', '2016-17', '2017-18', '2018-19', '2019-20', '2020-21', '2021-22', '2022-23']
val_season = '2023-24'
test_season = '2024-25'

train_data = load_data[load_data['season'].isin(train_seasons)]
val_data = load_data[load_data['season'] == val_season]
test_data = load_data[load_data['season'] == test_season]

# Separate features and target
X_train, y_train = train_data.drop('home_won', axis=1), train_data['home_won']
X_val, y_val = val_data.drop('home_won', axis=1), val_data['home_won']
X_test, y_test = test_data.drop('home_won', axis=1), test_data['home_won']

# Convert categorical columns (team names, season) to category dtype
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

# Train the model
basketball_model.train(X_train, y_train)

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

