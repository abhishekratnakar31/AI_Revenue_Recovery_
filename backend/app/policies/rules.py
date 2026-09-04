"""
Merchant Policy Rules Module

This module defines deterministic rules for evaluating proposed candidate actions against merchant policies.

Rules Defined:
1. Max Retries Rule: Ensures payment attempt count does not exceed merchant limit (max_retries).
2. Minimum Retry Interval Rule: Enforces waiting window (minimum_retry_interval) between retries.
3. Customer Fatigue Limit Rule: Ensures customer notifications in past 24 hours do not exceed max_notifications_per_24h.
4. Discount Cap Rule: Prevents offering discounts exceeding max_discount_percentage.
"""

import datetime
import logging
from typing import Tuple
from sqlalchemy.orm import Session

from backend.app.models.models import RecoveryCase, PaymentAttempt, NotificationEvent, MerchantPolicy
from backend.app.core.config import settings

logger = logging.getLogger(__name__)


def utc_now():
    """Returns timezone-aware UTC datetime."""
    return datetime.datetime.now(datetime.timezone.utc)


def check_max_retries_rule(db: Session, case: RecoveryCase, merchant_policy: MerchantPolicy) -> Tuple[bool, str]:
    """
    Checks if attempt count has reached or exceeded max_retries limit.
    """
    max_retries = merchant_policy.max_retries if merchant_policy else settings.DEFAULT_MAX_RETRIES
    attempt_count = db.query(PaymentAttempt).filter(PaymentAttempt.payment_id == case.payment_id).count() if case.payment_id else 1

    if attempt_count >= max_retries:
        return False, f"Payment attempt count ({attempt_count}) has reached merchant max retries limit ({max_retries})."
    return True, f"Attempt count ({attempt_count}) is within limit ({max_retries})."


def check_retry_interval_rule(db: Session, case: RecoveryCase, merchant_policy: MerchantPolicy) -> Tuple[bool, str]:
    """
    Checks if the minimum retry interval (in minutes) has elapsed since the last payment attempt.
    """
    min_interval_mins = merchant_policy.minimum_retry_interval if merchant_policy else settings.DEFAULT_MIN_RETRY_INTERVAL_MINUTES
    last_attempt = db.query(PaymentAttempt).filter(PaymentAttempt.payment_id == case.payment_id).order_by(PaymentAttempt.timestamp.desc()).first()

    if last_attempt and last_attempt.timestamp:
        last_time = last_attempt.timestamp.replace(tzinfo=datetime.timezone.utc) if last_attempt.timestamp.tzinfo is None else last_attempt.timestamp
        elapsed_mins = (utc_now() - last_time).total_seconds() / 60.0

        if elapsed_mins < min_interval_mins:
            return False, f"Only {elapsed_mins:.1f} minutes elapsed since last attempt. Required interval is {min_interval_mins} minutes."

    return True, f"Retry interval check passed."


def check_customer_fatigue_rule(db: Session, customer_id: int, merchant_policy: MerchantPolicy) -> Tuple[bool, str]:
    """
    Checks if notifications sent to the customer in the past 24 hours exceed max_notifications_per_24h.
    """
    max_notifs = merchant_policy.max_notifications_per_24h if merchant_policy else settings.DEFAULT_MAX_NOTIFICATIONS_PER_24H
    cutoff_24h = utc_now() - datetime.timedelta(hours=24)

    notif_count = db.query(NotificationEvent).filter(
        NotificationEvent.customer_id == customer_id,
        NotificationEvent.timestamp >= cutoff_24h
    ).count()

    if notif_count >= max_notifs:
        return False, f"Customer received {notif_count} notifications in the past 24 hours. Limit is {max_notifs}."
    return True, f"Customer notification count ({notif_count}/24h) is within limit ({max_notifs})."


def check_discount_cap_rule(proposed_discount: float, merchant_policy: MerchantPolicy) -> Tuple[bool, str]:
    """
    Checks if a proposed recovery discount exceeds merchant max_discount_percentage.
    """
    max_discount = merchant_policy.max_discount_percentage if merchant_policy else 10.0
    if proposed_discount > max_discount:
        return False, f"Proposed discount {proposed_discount:.1f}% exceeds merchant cap of {max_discount:.1f}%."
    return True, f"Proposed discount {proposed_discount:.1f}% is within cap ({max_discount:.1f}%)."


def check_gateway_degradation_rule(db: Session, case: RecoveryCase) -> Tuple[bool, str, str]:
    """
    Evaluates proposed RETRY action against statistical route degradation status (Milestone 11).
    Returns (passed, reason, decision_code).
    """
    from backend.app.models.models import Payment, PaymentAttempt, GatewayRouteStatus
    from backend.app.analytics.degradation import normalize_route, utc_now

    # Fetch last payment attempt or payment metadata
    attempt = None
    if case.payment_id:
        attempt = db.query(PaymentAttempt).filter(
            PaymentAttempt.payment_id == case.payment_id
        ).order_by(PaymentAttempt.timestamp.desc()).first()

    payment = db.query(Payment).filter(Payment.id == case.payment_id).first() if case.payment_id else None

    gw = getattr(attempt, "gateway", None) or getattr(payment, "gateway", "razorpay")
    pm = getattr(attempt, "payment_method", None) or getattr(payment, "payment_method", "CARD")
    b = getattr(attempt, "bank", None) or "UNKNOWN"

    gw_norm, pm_norm, b_norm = normalize_route(gw, pm, b)

    route_status = db.query(GatewayRouteStatus).filter(
        GatewayRouteStatus.gateway == gw_norm,
        GatewayRouteStatus.payment_method == pm_norm,
        GatewayRouteStatus.bank == b_norm,
    ).first()

    if not route_status or route_status.status == "NORMAL":
        return True, f"Route ({gw_norm}, {pm_norm}, {b_norm}) is operating normally.", "ALLOW"

    if route_status.status == "SUSPECTED":
        return True, f"Route ({gw_norm}, {pm_norm}, {b_norm}) is SUSPECTED degraded (Z={route_status.current_z_score:.2f}). Retry allowed under observation.", "ALLOW"

    if route_status.status == "CONFIRMED":
        return False, f"Route ({gw_norm}, {pm_norm}, {b_norm}) is experiencing CONFIRMED degradation (Z={route_status.current_z_score:.2f}). Direct retries paused.", "BLOCK"

    if route_status.status == "RECOVERING":
        now = utc_now()
        last_probe = route_status.last_probe_at
        if last_probe:
            last_p_time = last_probe.replace(tzinfo=datetime.timezone.utc) if last_probe.tzinfo is None else last_probe
            elapsed_sec = (now - last_p_time).total_seconds()
            if elapsed_sec < 300:
                return False, f"Route ({gw_norm}, {pm_norm}, {b_norm}) recovering; probe slot used {elapsed_sec:.0f}s ago (required: 300s).", "BLOCK"

        return True, f"Route ({gw_norm}, {pm_norm}, {b_norm}) recovering; probe slot granted.", "ALLOW_PROBE"

    return True, f"Route operating normally.", "ALLOW"

