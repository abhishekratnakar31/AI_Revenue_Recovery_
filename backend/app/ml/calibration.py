"""Probability calibration metrics, segment-level evaluation, and reliability utilities."""

from typing import Dict, Any, Tuple, List
import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.calibration import calibration_curve


def evaluate_calibration(
    y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10
) -> Dict[str, Any]:
    """Compute calibration and probability accuracy metrics.
    
    Args:
        y_true: True binary target labels (0 or 1).
        y_prob: Predicted probabilities in [0, 1].
        n_bins: Number of bins for reliability diagram.
        
    Returns:
        Dictionary containing brier_score, log_loss, roc_auc, and calibration error.
    """
    brier = float(brier_score_loss(y_true, y_prob))
    ll = float(log_loss(y_true, y_prob))
    try:
        auc = float(roc_auc_score(y_true, y_prob))
    except ValueError:
        auc = 0.5  # Single class edge case fallback

    prob_true, prob_pred = calibration_curve(y_true, y_prob, n_bins=n_bins, strategy="uniform")
    calibration_error = float(np.mean(np.abs(prob_true - prob_pred))) if len(prob_true) > 0 else 0.0

    return {
        "brier_score": brier,
        "log_loss": ll,
        "roc_auc": auc,
        "calibration_error": calibration_error,
        "calibration_curve": {
            "prob_true": prob_true.tolist(),
            "prob_pred": prob_pred.tolist(),
        },
    }


def evaluate_raw_vs_calibrated(
    y_true: np.ndarray, raw_probs: np.ndarray, calibrated_probs: np.ndarray
) -> Dict[str, Dict[str, float]]:
    """Compare performance metrics between uncalibrated raw model and calibrated model."""
    raw_eval = evaluate_calibration(y_true, raw_probs)
    cal_eval = evaluate_calibration(y_true, calibrated_probs)

    return {
        "raw_model": {
            "brier_score": raw_eval["brier_score"],
            "log_loss": raw_eval["log_loss"],
            "roc_auc": raw_eval["roc_auc"],
            "calibration_error": raw_eval["calibration_error"],
        },
        "calibrated_model": {
            "brier_score": cal_eval["brier_score"],
            "log_loss": cal_eval["log_loss"],
            "roc_auc": cal_eval["roc_auc"],
            "calibration_error": cal_eval["calibration_error"],
        },
    }


def evaluate_segment_metrics(
    df: pd.DataFrame, y_true: np.ndarray, y_prob: np.ndarray, segment_column: str
) -> Dict[str, Dict[str, float]]:
    """Evaluate Brier Score and ROC-AUC broken down by specific feature segments."""
    segment_results = {}
    unique_segments = df[segment_column].unique()

    for seg in unique_segments:
        mask = (df[segment_column] == seg).values
        if np.sum(mask) >= 10:  # Minimum sample size threshold
            seg_y_true = y_true[mask]
            seg_y_prob = y_prob[mask]
            
            brier = float(brier_score_loss(seg_y_true, seg_y_prob))
            try:
                auc = float(roc_auc_score(seg_y_true, seg_y_prob))
            except ValueError:
                auc = 0.5

            segment_results[str(seg)] = {
                "sample_count": int(np.sum(mask)),
                "brier_score": brier,
                "roc_auc": auc,
            }

    return segment_results
