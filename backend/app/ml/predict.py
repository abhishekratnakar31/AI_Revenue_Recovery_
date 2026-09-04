"""Prediction service for RecoverAI ML probability estimation and audit logging.

Includes in-memory model caching (singleton) to avoid redundant disk I/O,
and empirical failure-reason baseline fallbacks when model files are absent.
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session

from backend.app.models.models import ModelPrediction, RecoveryCase
from backend.app.ml.features import extract_features_from_case
from backend.app.ml.schemas import PredictionOutput, MLFeatureVector
from backend.app.ml.model import RecoveryModel

logger = logging.getLogger(__name__)

DEFAULT_MODEL_PATH: str = "ml/artifacts/recovery_model.pkl"

# Singleton in-memory model cache to prevent repeated disk loading
_CACHED_MODEL: Optional[RecoveryModel] = None
_CACHED_MODEL_PATH: Optional[str] = None


def get_cached_model(model_path: str = DEFAULT_MODEL_PATH) -> Optional[RecoveryModel]:
    """Retrieve or load cached RecoveryModel singleton."""
    global _CACHED_MODEL, _CACHED_MODEL_PATH
    if _CACHED_MODEL is not None and _CACHED_MODEL_PATH == model_path:
        return _CACHED_MODEL

    if os.path.exists(model_path):
        try:
            _CACHED_MODEL = RecoveryModel.load(model_path)
            _CACHED_MODEL_PATH = model_path
            return _CACHED_MODEL
        except Exception as e:
            logger.warning(f"Failed to load ML model from {model_path}: {e}")
            return None
    return None


def clear_model_cache():
    """Clear in-memory model cache (used for unit tests and model reloads)."""
    global _CACHED_MODEL, _CACHED_MODEL_PATH
    _CACHED_MODEL = None
    _CACHED_MODEL_PATH = None


def predict_recovery_probability(
    db: Session,
    case_id: int,
    model_path: str = DEFAULT_MODEL_PATH,
) -> PredictionOutput:
    """Predict calibrated probability P(recovery) for a given RecoveryCase.
    
    Persists prediction audit log into model_predictions PostgreSQL table.
    Uses cached in-memory model singleton for high throughput.
    Falls back to empirical failure-reason baselines if model artifact is absent.
    
    Args:
        db: SQLAlchemy database session.
        case_id: RecoveryCase primary key.
        model_path: Path to serialized RecoveryModel .pkl artifact.
        
    Returns:
        PredictionOutput Pydantic schema instance.
    """
    vector = extract_features_from_case(db, case_id)

    model = get_cached_model(model_path)
    prediction_output: Optional[PredictionOutput] = None

    if model is not None:
        try:
            prediction_output = model.predict_single(vector)
        except Exception as e:
            logger.warning(f"Model inference failed for case {case_id}: {e}")

    # Empirical Baseline Fallback (based on empirical failure-reason historical recovery rates)
    if prediction_output is None:
        empirical_fallbacks = {
            "BANK_TIMEOUT": 0.41,
            "INSUFFICIENT_FUNDS": 0.23,
            "AUTH_FAILURE": 0.31,
            "EXPIRED_CARD": 0.08,
        }
        fallback_p = empirical_fallbacks.get(vector.failure_reason, 0.28)

        prediction_output = PredictionOutput(
            probability=fallback_p,
            model_version="fallback-v1",
            model_type="FallbackBaseline",
            calibration_method="none",
            prediction_source="FALLBACK",
        )

    # Persist prediction audit log into PostgreSQL
    db_prediction = ModelPrediction(
        recovery_case_id=case_id,
        model_name=prediction_output.model_type,
        model_version=prediction_output.model_version,
        prediction=prediction_output.probability,
        feature_version="v1",
        predicted_at=datetime.now(timezone.utc),
    )
    db.add(db_prediction)
    
    # Also update recovery_probability on RecoveryCase
    case = db.query(RecoveryCase).filter(RecoveryCase.id == case_id).first()
    if case:
        case.recovery_probability = prediction_output.probability

    db.commit()

    return prediction_output
