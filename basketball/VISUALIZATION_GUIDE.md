# Basketball Model Visualization Guide

## Overview
The `BasketballModel` class now includes comprehensive diagnostic plots and checks to verify model performance and predictions.

## Available Visualizations

### 1. **Feature Importance Plot** (`feature_importance.png`)
- Shows the top 20 most important features used by the model
- Helps identify which statistics have the most impact on predictions
- **Use case**: Understand what drives your model's decisions

### 2. **ROC Curves** (`roc_curves.png`)
- Compares model performance on validation and test sets
- Shows the trade-off between true positive rate and false positive rate
- Includes AUC scores for both sets
- **Use case**: Assess overall model discrimination ability

### 3. **Calibration Plot** (`calibration_plot.png`)
- Shows if predicted probabilities match actual win rates
- Perfect calibration = points on diagonal line
- **Use case**: Check if a 70% predicted probability actually means 70% chance of winning
- **Critical for betting**: Well-calibrated probabilities are essential for expected value calculations

### 4. **Confusion Matrices** (`confusion_matrices.png`)
- Shows true positives, false positives, true negatives, false negatives
- Side-by-side comparison of validation and test sets
- **Use case**: Identify if model has bias toward home/away predictions

### 5. **Prediction Distribution** (`prediction_distribution.png`)
- Histogram of all predicted probabilities
- Shows if model is confident or tends toward 50/50 predictions
- **Use case**: Identify if model makes decisive predictions or is uncertain

### 6. **Confidence vs Accuracy** (`confidence_accuracy.png`)
- Shows accuracy at different confidence levels
- Includes sample count for each confidence bin
- **Use case**: Determine if high-confidence predictions are actually more accurate
- **Critical for betting**: Only bet on high-confidence predictions if they're actually more accurate

## Usage

### Running All Diagnostics
```python
# After training the model
basketball_model.plot_diagnostics(X_val, y_val, X_test, y_test, save_dir='./plots/basketball')
```

This generates all 6 plots and saves them to the specified directory.

### Prediction Summary
```python
# Print detailed statistics about predictions
basketball_model.print_prediction_summary(X_test, y_test)
```

This prints:
- Total predictions and home/away win distribution
- Confidence level distribution (high/medium/low)
- Accuracy on high-confidence predictions
- Comparison of predicted vs actual win rates

## What to Look For

### ✅ Good Signs
- **Calibration**: Points close to diagonal line
- **ROC Curve**: AUC > 0.75 (current: ~0.79-0.80)
- **Confidence vs Accuracy**: Higher confidence = higher accuracy
- **Prediction Distribution**: Spread across probability range (not all near 0.5)

### ⚠️ Warning Signs
- **Calibration**: Systematic deviation from diagonal (over/under-confident)
- **Confusion Matrix**: Heavy bias toward one class
- **Confidence vs Accuracy**: High confidence but low accuracy (overconfident model)
- **Prediction Distribution**: All predictions near 0.5 (model is uncertain)

## Betting Strategy Implications

1. **Use Calibration Plot**: If model is well-calibrated, probabilities can be used directly for expected value calculations
2. **Check Confidence-Accuracy**: Only bet when model is both confident AND accurate at that confidence level
3. **Monitor Feature Importance**: Ensure model relies on meaningful features, not noise
4. **Track Distribution**: If all predictions are near 0.5, model may not have edge

## Example Workflow

```python
# 1. Train model
basketball_model.train(X_train, y_train)

# 2. Evaluate
val_metrics = basketball_model.evaluate(X_val, y_val)
test_metrics = basketball_model.evaluate(X_test, y_test)

# 3. Generate all diagnostic plots
basketball_model.plot_diagnostics(X_val, y_val, X_test, y_test)

# 4. Review prediction summary
basketball_model.print_prediction_summary(X_test, y_test)

# 5. Review plots in ./plots/basketball/ directory
# 6. Make decisions about model deployment based on diagnostics
```

## Dependencies
- matplotlib
- seaborn
- sklearn (for metrics)
- numpy
- pandas

All plots are saved as high-resolution PNG files (300 DPI) suitable for reports or presentations.
