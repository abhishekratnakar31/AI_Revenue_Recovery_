"""Training pipeline CLI script for RecoverAI ML model."""

import os
import sys
from datetime import datetime, timezone
import numpy as np

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.app.ml.dataset import generate_historical_dataset, temporal_split
from backend.app.ml.model import RecoveryModel
from backend.app.ml.calibration import evaluate_calibration, evaluate_raw_vs_calibrated, evaluate_segment_metrics
from backend.app.ml.preprocessing import NUMERICAL_FEATURES, CATEGORICAL_FEATURES


def run_training(
    num_samples: int = 50000,
    model_output_path: str = "ml/artifacts/recovery_model.pkl",
    calibration_method: str = "isotonic",
):
    """Execute complete model training, calibration, evaluation, and artifact saving.
    
    Args:
        num_samples: Size of synthetic historical training dataset.
        model_output_path: File path to write .pkl artifact.
        calibration_method: Calibration algorithm ('isotonic' or 'sigmoid').
    """
    print(f"[ML Train] Generating {num_samples} historical simulation records...")
    df = generate_historical_dataset(num_samples=num_samples, random_seed=42)

    print("[ML Train] Performing temporal train/val/test split...")
    train_df, val_df, test_df = temporal_split(df, train_ratio=0.70, val_ratio=0.15, test_ratio=0.15)

    print(f"  - Train split: {len(train_df)} rows ({train_df['feature_timestamp'].min()} to {train_df['feature_timestamp'].max()})")
    print(f"  - Val split:   {len(val_df)} rows ({val_df['feature_timestamp'].min()} to {val_df['feature_timestamp'].max()})")
    print(f"  - Test split:  {len(test_df)} rows ({test_df['feature_timestamp'].min()} to {test_df['feature_timestamp'].max()})")

    # Assert temporal ordering
    assert train_df["feature_timestamp"].max() < val_df["feature_timestamp"].min()
    assert val_df["feature_timestamp"].max() < test_df["feature_timestamp"].min()

    print(f"[ML Train] Fitting RecoveryModel with XGBoost + {calibration_method} calibration...")
    model = RecoveryModel(calibration_method=calibration_method)
    model.fit(train_df, val_df)

    print("[ML Train] Evaluating model on unseen test split...")
    test_probs = model.predict_proba(test_df)
    y_test = test_df["target"].values

    metrics = evaluate_calibration(y_test, test_probs)

    # Historical Mean Baseline comparison
    baseline_p = float(train_df["target"].mean())
    baseline_probs = np.full_like(y_test, fill_value=baseline_p, dtype=float)
    baseline_metrics = evaluate_calibration(y_test, baseline_probs)

    print("\n--- Baseline vs RecoverAI Model Comparison ---")
    print(f"  - Baseline Mean Brier Score: {baseline_metrics['brier_score']:.4f}")
    print(f"  - RecoverAI Model Brier:     {metrics['brier_score']:.4f} (Error Reduction: {((baseline_metrics['brier_score'] - metrics['brier_score']) / baseline_metrics['brier_score']) * 100:.1f}%)")
    print(f"  - RecoverAI Model ROC-AUC:   {metrics['roc_auc']:.4f}")
    print(f"  - Calibration Error:         {metrics['calibration_error']:.4f}")

    print("\n--- Segment-Level Performance Breakdown (Payment Method) ---")
    method_metrics = evaluate_segment_metrics(test_df, y_test, test_probs, "payment_method")
    for method, res in method_metrics.items():
        print(f"  - {method:12s}: N={res['sample_count']:4d} | Brier={res['brier_score']:.4f} | ROC-AUC={res['roc_auc']:.4f}")

    print("\n--- Segment-Level Performance Breakdown (Failure Reason) ---")
    reason_metrics = evaluate_segment_metrics(test_df, y_test, test_probs, "failure_reason")
    for reason, res in reason_metrics.items():
        print(f"  - {reason:18s}: N={res['sample_count']:4d} | Brier={res['brier_score']:.4f} | ROC-AUC={res['roc_auc']:.4f}")

    print(f"\n[ML Train] Saving model artifact to {model_output_path}...")
    model.save(model_output_path)
    print("[ML Train] Model training and artifact serialization complete successfully!")


if __name__ == "__main__":
    run_training()
