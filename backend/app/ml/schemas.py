"""Pydantic schemas for RecoverAI ML feature vectors and prediction outputs."""

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class MLFeatureVector(BaseModel):
    """Raw business feature vector for ML model prediction.
    
    Strictly restricted to features known at or before feature_timestamp.
    Does NOT contain future variables, targets, or actions.
    """
    feature_timestamp: datetime = Field(
        description="Timestamp boundary at which the snapshot is valid."
    )
    amount: float = Field(
        ge=0.0, description="Order amount in currency units (e.g. INR)."
    )
    customer_ltv: float = Field(
        ge=0.0, description="Customer Lifetime Value prior to this payment."
    )
    customer_failure_count_30d: int = Field(
        ge=0, description="Number of failed payments for this customer in last 30 days."
    )
    customer_success_count_90d: int = Field(
        ge=0, description="Number of successful payments for this customer in last 90 days."
    )
    attempt_number: int = Field(
        ge=1, description="Payment attempt sequence number for this order."
    )
    hour: int = Field(
        ge=0, le=23, description="Hour of the day (0-23) when failure occurred."
    )
    day_of_week: int = Field(
        ge=0, le=6, description="Day of week (0=Monday, 6=Sunday)."
    )
    payment_method: Literal["UPI", "CARD", "NETBANKING", "UNKNOWN"] = Field(
        description="Payment method used for the failed attempt."
    )
    failure_reason: Literal[
        "BANK_TIMEOUT", "INSUFFICIENT_FUNDS", "AUTH_FAILURE", "EXPIRED_CARD", "UNKNOWN"
    ] = Field(description="Gateway failure error code.")
    subscription: bool = Field(
        default=False, description="Whether this payment is for a recurring subscription."
    )


class PredictionOutput(BaseModel):
    """Output prediction payload returned by RecoveryModel or fallback service."""
    probability: float = Field(
        ge=0.0, le=1.0, description="Calibrated probability P(natural recovery | context)."
    )
    model_version: str = Field(
        description="Version tag of the ML model artifact (e.g., 'recovery-xgb-v1')."
    )
    model_type: str = Field(
        description="Algorithm type (e.g., 'XGBoost', 'FallbackBaseline')."
    )
    calibration_method: str = Field(
        description="Calibration approach used (e.g., 'isotonic', 'sigmoid', 'none')."
    )
    prediction_source: Literal["ML", "FALLBACK"] = Field(
        description="Origin of prediction: ML model vs deterministic fallback."
    )
