"""RecoveryModel class wrapping XGBoost Classifier and probability calibration."""

import os
import json
import joblib
from typing import Optional, Dict, Any, List
import pandas as pd
import numpy as np

try:
    from xgboost import XGBClassifier
    HAS_XGBOOST = True
except Exception:
    HAS_XGBOOST = False
    from sklearn.ensemble import HistGradientBoostingClassifier

from sklearn.calibration import CalibratedClassifierCV

from backend.app.ml.preprocessing import build_preprocessor, NUMERICAL_FEATURES, CATEGORICAL_FEATURES
from backend.app.ml.schemas import MLFeatureVector, PredictionOutput


MODEL_VERSION: str = "recovery-xgb-v1"


class RecoveryModel:
    """XGBoost / Gradient Boosting Classifier with Probability Calibration for Payment Recovery Estimation.
    
    Coupled with a ColumnTransformer preprocessor and feature_metadata.json for
    strict production schema enforcement.
    """

    def __init__(self, calibration_method: str = "isotonic"):
        self.model_version = MODEL_VERSION
        self.calibration_method = calibration_method
        self.algorithm_name = "XGBoost" if HAS_XGBOOST else "HistGradientBoosting"
        self.empirical_fallbacks: Dict[str, float] = {}
        self.preprocessor = build_preprocessor()
        
        if HAS_XGBOOST:
            self.base_model = XGBClassifier(
                n_estimators=100,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                random_state=42,
                eval_metric="logloss"
            )
        else:
            self.base_model = HistGradientBoostingClassifier(
                max_iter=100,
                max_depth=4,
                learning_rate=0.05,
                random_state=42
            )
        self.calibrated_model: Optional[CalibratedClassifierCV] = None

    def fit(self, train_df: pd.DataFrame, val_df: Optional[pd.DataFrame] = None):
        """Fit preprocessor, train model, and calibrate probabilities.
        
        Args:
            train_df: Training DataFrame containing features and 'target'.
            val_df: Optional validation DataFrame.
        """
        # Calculate empirical fallbacks from training data
        if "failure_reason" in train_df.columns and "target" in train_df.columns:
            fallbacks = train_df.groupby("failure_reason")["target"].mean().to_dict()
            self.empirical_fallbacks = {str(k): round(float(v), 4) for k, v in fallbacks.items()}

        X_raw = train_df[NUMERICAL_FEATURES + CATEGORICAL_FEATURES]
        y = train_df["target"].values

        # 1. Fit ColumnTransformer
        X_trans = self.preprocessor.fit_transform(X_raw)

        # 2. Fit CalibratedClassifierCV with cross-validation
        self.calibrated_model = CalibratedClassifierCV(
            estimator=self.base_model,
            method=self.calibration_method,
            cv=5
        )
        self.calibrated_model.fit(X_trans, y)

    def predict_proba(self, feature_df: pd.DataFrame) -> np.ndarray:
        """Predict calibrated probabilities for input feature DataFrame.
        
        Returns:
            1D numpy array of probabilities P(recovery) in [0.0, 1.0].
        """
        if self.calibrated_model is None:
            raise RuntimeError("Model is not fitted. Call fit() or load() first.")

        X_raw = feature_df[NUMERICAL_FEATURES + CATEGORICAL_FEATURES]
        X_trans = self.preprocessor.transform(X_raw)
        probas = self.calibrated_model.predict_proba(X_trans)
        return probas[:, 1]  # Return probability of target=1

    def predict_single(self, vector: MLFeatureVector) -> PredictionOutput:
        """Predict calibrated probability for a single MLFeatureVector instance."""
        from backend.app.ml.preprocessing import feature_vector_to_dict
        df = pd.DataFrame([feature_vector_to_dict(vector)])
        prob = float(self.predict_proba(df)[0])
        prob_clipped = max(0.0, min(1.0, prob))

        return PredictionOutput(
            probability=prob_clipped,
            model_version=self.model_version,
            model_type=self.algorithm_name,
            calibration_method=self.calibration_method,
            prediction_source="ML"
        )

    def save(self, model_path: str):
        """Save model artifact (.pkl) and feature metadata (.json)."""
        os.makedirs(os.path.dirname(model_path), exist_ok=True)
        joblib.dump(self, model_path)

        metadata_path = os.path.join(os.path.dirname(model_path), "feature_metadata.json")
        metadata = {
            "model_version": self.model_version,
            "algorithm": self.algorithm_name,
            "calibration_method": self.calibration_method,
            "empirical_fallbacks": self.empirical_fallbacks,
            "numerical_features": NUMERICAL_FEATURES,
            "categorical_features": CATEGORICAL_FEATURES,
        }
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

    @classmethod
    def load(cls, model_path: str) -> "RecoveryModel":
        """Load trained RecoveryModel artifact from disk."""
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model artifact not found at {model_path}")
        model = joblib.load(model_path)
        return model
