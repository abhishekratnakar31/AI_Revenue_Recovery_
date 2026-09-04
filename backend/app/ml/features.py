"""Feature extraction engine for RecoverAI ML pipeline.

Enforces strict temporal boundary (feature_timestamp). No future attributes,
action selections, post-failure attempts, or recovery outcomes are included.
Historical counts strictly require timestamp < feature_timestamp (strictly prior).
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.app.models.models import RecoveryCase, Customer, PaymentAttempt, Payment, Order
from backend.app.ml.schemas import MLFeatureVector


def ensure_utc(dt: Optional[datetime]) -> datetime:
    """Helper to convert naive datetimes to UTC or supply default."""
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def extract_features_from_case(db: Session, case_id: int) -> MLFeatureVector:
    """Extract zero-leakage MLFeatureVector from PostgreSQL DB for a given case_id.
    
    Historical aggregations filter records strictly PRIOR to feature_timestamp (timestamp < feature_timestamp).
    The current failed attempt is NOT counted as part of historical failure count.
    
    Args:
        db: SQLAlchemy database session.
        case_id: Primary key of RecoveryCase.
        
    Returns:
        MLFeatureVector validated Pydantic model instance.
    """
    case = db.query(RecoveryCase).filter(RecoveryCase.id == case_id).first()
    if not case:
        raise ValueError(f"RecoveryCase with id {case_id} not found.")

    # Determine authoritative failure timestamp from originating or initial payment attempt
    originating_attempt = None
    if hasattr(case, "originating_attempt_id") and case.originating_attempt_id:
        originating_attempt = db.query(PaymentAttempt).filter(PaymentAttempt.id == case.originating_attempt_id).first()

    first_attempt = originating_attempt or db.query(PaymentAttempt).filter(
        PaymentAttempt.payment_id == case.payment_id
    ).order_by(PaymentAttempt.timestamp.asc()).first()

    if first_attempt:
        feature_ts = ensure_utc(first_attempt.timestamp)
    else:
        feature_ts = ensure_utc(case.created_at)

    # 1. Historical Customer LTV prior to feature_ts (strictly < feature_ts)
    customer = None
    customer_ltv = 0.0
    if case.customer_id:
        customer = db.query(Customer).filter(Customer.id == case.customer_id).first()
        
    if customer:
        hist_ltv = db.query(func.sum(Order.amount)).join(Payment).filter(
            Order.customer_id == customer.id,
            Payment.status == "CAPTURED",
            Payment.captured_at < feature_ts  # Strictly prior to failure
        ).scalar()
        customer_ltv = float(hist_ltv) if hist_ltv is not None else 0.0

    # 2. Aggregate failures in past 30 days strictly PRIOR to feature_ts (< feature_ts)
    window_30d = feature_ts - timedelta(days=30)
    customer_failure_count_30d = 0
    if customer:
        customer_failure_count_30d = db.query(PaymentAttempt).join(Payment).join(Order).filter(
            Order.customer_id == customer.id,
            PaymentAttempt.status == "FAILED",
            PaymentAttempt.timestamp >= window_30d,
            PaymentAttempt.timestamp < feature_ts  # Strictly prior (excludes current failure!)
        ).count()

    # 3. Aggregate successes in past 90 days strictly PRIOR to feature_ts (< feature_ts)
    window_90d = feature_ts - timedelta(days=90)
    customer_success_count_90d = 0
    if customer:
        customer_success_count_90d = db.query(Payment).join(Order).filter(
            Order.customer_id == customer.id,
            Payment.status == "CAPTURED",
            Payment.captured_at >= window_90d,
            Payment.captured_at < feature_ts  # Strictly prior
        ).count()

    # 4. Extract attempt context at or before feature_ts
    attempts_at_ts = db.query(PaymentAttempt).filter(
        PaymentAttempt.payment_id == case.payment_id,
        PaymentAttempt.timestamp <= feature_ts
    ).order_by(PaymentAttempt.timestamp.asc()).all()

    attempt_number = max(len(attempts_at_ts), 1)
    latest_attempt = attempts_at_ts[-1] if attempts_at_ts else first_attempt
    raw_method = latest_attempt.payment_method.upper() if latest_attempt and latest_attempt.payment_method else "UNKNOWN"
    if raw_method not in ["UPI", "CARD", "NETBANKING"]:
        raw_method = "UNKNOWN"

    raw_reason = latest_attempt.failure_reason.upper() if latest_attempt and latest_attempt.failure_reason else "UNKNOWN"
    valid_reasons = ["BANK_TIMEOUT", "INSUFFICIENT_FUNDS", "AUTH_FAILURE", "EXPIRED_CARD"]
    if raw_reason not in valid_reasons:
        raw_reason = "UNKNOWN"

    hour = feature_ts.hour
    day_of_week = feature_ts.weekday()
    subscription = case.subscription_id is not None

    return MLFeatureVector(
        feature_timestamp=feature_ts,
        amount=float(case.amount_at_risk),
        customer_ltv=customer_ltv,
        customer_failure_count_30d=customer_failure_count_30d,
        customer_success_count_90d=customer_success_count_90d,
        attempt_number=attempt_number,
        hour=hour,
        day_of_week=day_of_week,
        payment_method=raw_method,
        failure_reason=raw_reason,
        subscription=subscription
    )
