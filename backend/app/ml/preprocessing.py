"""Preprocessing pipeline for RecoverAI ML model matrix transformation."""

from typing import List, Dict, Any
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder

from backend.app.ml.schemas import MLFeatureVector

NUMERICAL_FEATURES: List[str] = [
    "amount",
    "customer_ltv",
    "customer_failure_count_30d",
    "customer_success_count_90d",
    "attempt_number",
    "hour",
    "day_of_week",
    "subscription",
]

CATEGORICAL_FEATURES: List[str] = [
    "payment_method",
    "failure_reason",
]


def build_preprocessor() -> ColumnTransformer:
    """Build scikit-learn ColumnTransformer for ML feature vector processing.
    
    Uses handle_unknown='ignore' on OneHotEncoder to gracefully process unseen
    categorical values in production without crashing.
    """
    preprocessor = ColumnTransformer(
        transformers=[
            ("num", "passthrough", NUMERICAL_FEATURES),
            (
                "cat",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                CATEGORICAL_FEATURES,
            ),
        ],
        remainder="drop",
    )
    return preprocessor


def feature_vector_to_dict(vector: MLFeatureVector) -> Dict[str, Any]:
    """Convert MLFeatureVector model instance to dictionary for DataFrame ingestion."""
    return {
        "amount": vector.amount,
        "customer_ltv": vector.customer_ltv,
        "customer_failure_count_30d": vector.customer_failure_count_30d,
        "customer_success_count_90d": vector.customer_success_count_90d,
        "attempt_number": vector.attempt_number,
        "hour": vector.hour,
        "day_of_week": vector.day_of_week,
        "subscription": 1 if vector.subscription else 0,
        "payment_method": vector.payment_method,
        "failure_reason": vector.failure_reason,
    }


def feature_vectors_to_dataframe(vectors: List[MLFeatureVector]) -> pd.DataFrame:
    """Convert list of MLFeatureVector instances into pandas DataFrame."""
    dicts = [feature_vector_to_dict(v) for v in vectors]
    return pd.DataFrame(dicts)
