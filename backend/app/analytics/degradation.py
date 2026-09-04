"""
Statistical Gateway Degradation Detector for RecoverAI (Milestone 11).

Monitors transaction outcomes by canonical 3-tuple route (gateway, payment_method, bank)
using rolling 15-minute windows and division-by-zero safe Z-score anomaly detection.
Enforces mutually exclusive 4-state lifecycle (NORMAL, SUSPECTED, CONFIRMED, RECOVERING).
"""

import math
import logging
from abc import ABC, abstractmethod
from typing import Tuple, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from backend.app.models.models import GatewayRouteStatus, PaymentAttempt, AuditLog

logger = logging.getLogger("recoverai.analytics.degradation")


def utc_now() -> datetime:
    """Returns timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def normalize_route(gateway: Optional[str], payment_method: Optional[str], bank: Optional[str]) -> Tuple[str, str, str]:
    """
    Normalizes route components to canonical forms:
    - gateway: lowercase (e.g. "razorpay")
    - payment_method: uppercase (e.g. "UPI", "CARD")
    - bank: uppercase, or "UNKNOWN" if missing/blank/None (e.g. "HDFC")
    """
    norm_gw = (gateway or "razorpay").strip().lower()
    norm_pm = (payment_method or "CARD").strip().upper()

    clean_bank = (bank or "").strip().upper()
    if not clean_bank or clean_bank in ("NONE", "NULL", "UNKNOWN"):
        clean_b = "UNKNOWN"
    else:
        clean_b = clean_bank

    return norm_gw, norm_pm, clean_b


def classify_attempt_outcome(status: Optional[str]) -> Optional[str]:
    """
    Classifies raw gateway attempt status into canonical outcomes:
    - 'SUCCESS': captured, authorized
    - 'FAILURE': failed, timeout, expired, cancelled
    - None: created, initiated, pending (non-final, excluded from stats)
    """
    if not status:
        return None
    st = status.strip().lower()
    if st in ("captured", "authorized", "success", "captured_at"):
        return "SUCCESS"
    elif st in ("failed", "timeout", "expired", "cancelled", "bank_timeout", "gateway_down"):
        return "FAILURE"
    return None


class BaselineProvider(ABC):
    """Abstract interface for baseline failure rate providers."""

    @abstractmethod
    def get_baseline_failure_rate(self, gateway: str, payment_method: str, bank: str) -> float:
        """Returns baseline failure rate for a route [0.0 - 1.0]."""
        pass


class FixedBaselineProvider(BaselineProvider):
    """Fixed baseline failure rate provider (default 5% / 0.05)."""

    def __init__(self, default_rate: float = 0.05):
        self.default_rate = max(0.01, min(0.99, default_rate))

    def get_baseline_failure_rate(self, gateway: str, payment_method: str, bank: str) -> float:
        return self.default_rate


def compute_z_score(failed_count: int, total_count: int, baseline_rate: float = 0.05) -> Tuple[float, float]:
    """
    Computes standard error and one-sided Z-score for proportion test.
    SE = sqrt(p0 * (1 - p0) / N)
    Z = (F_window - p0) / SE
    Returns (z_score, failure_rate). Returns (0.0, 0.0) if total_count == 0.
    """
    if total_count <= 0:
        return 0.0, 0.0

    p0 = max(0.01, min(0.99, baseline_rate))
    failure_rate = failed_count / float(total_count)

    se = math.sqrt((p0 * (1.0 - p0)) / float(total_count))
    if se <= 0.0:
        return 0.0, failure_rate

    z_score = (failure_rate - p0) / se
    return round(z_score, 4), round(failure_rate, 4)


class GatewayDegradationDetector:
    """
    Event-driven statistical detector for route health and degradation state transitions.
    """

    def __init__(self, baseline_provider: Optional[BaselineProvider] = None):
        self.baseline_provider = baseline_provider or FixedBaselineProvider(0.05)

    def record_payment_attempt_event(self, db: Session, attempt: PaymentAttempt) -> Optional[GatewayRouteStatus]:
        """
        Records a new payment attempt event and evaluates route status.
        Ignores non-final attempt statuses.
        """
        outcome = classify_attempt_outcome(attempt.status)
        if not outcome:
            return None  # Non-final outcome, ignore for degradation stats

        gw, pm, b = normalize_route(attempt.gateway, attempt.payment_method, attempt.bank)
        return self.evaluate_route_status(db, gw, pm, b)

    def evaluate_route_status(
        self,
        db: Session,
        gateway: str,
        payment_method: str,
        bank: str,
        window_minutes: int = 15,
    ) -> GatewayRouteStatus:
        """
        Evaluates 15-minute rolling window statistics and executes mutually-exclusive state transitions.
        """
        gw, pm, b = normalize_route(gateway, payment_method, bank)
        p0 = self.baseline_provider.get_baseline_failure_rate(gw, pm, b)

        now = utc_now()
        window_start = now - timedelta(minutes=window_minutes)

        # Query PaymentAttempt events in rolling window using event occurrence timestamp
        attempts = db.query(PaymentAttempt).filter(
            PaymentAttempt.gateway == gw,
            PaymentAttempt.payment_method == pm,
            PaymentAttempt.bank == b,
            PaymentAttempt.timestamp >= window_start,
        ).all()

        # Classify outcomes and deduplicate by attempt ID
        seen_ids = set()
        total_count = 0
        failed_count = 0

        for att in attempts:
            if att.id in seen_ids:
                continue
            seen_ids.add(att.id)
            outcome = classify_attempt_outcome(att.status)
            if outcome == "FAILURE":
                total_count += 1
                failed_count += 1
            elif outcome == "SUCCESS":
                total_count += 1

        z_score, failure_rate = compute_z_score(failed_count, total_count, p0)

        # Query or create GatewayRouteStatus DB record with row locking
        route_status = db.query(GatewayRouteStatus).filter(
            GatewayRouteStatus.gateway == gw,
            GatewayRouteStatus.payment_method == pm,
            GatewayRouteStatus.bank == b,
        ).with_for_update().first()

        if not route_status:
            route_status = GatewayRouteStatus(
                gateway=gw,
                payment_method=pm,
                bank=b,
                status="NORMAL",
                baseline_failure_rate=p0,
                last_evaluated_at=now,
                last_state_change=now,
            )
            db.add(route_status)
            db.flush()

        old_state = route_status.status
        new_state = old_state

        # Mutually Exclusive 4-State Transition Logic
        # State 1: CONFIRMED (Evaluated 1st)
        if total_count >= 20 and z_score > 2.5 and failure_rate > p0:
            new_state = "CONFIRMED"

        # State 2: RECOVERING (Evaluated 2nd)
        elif old_state == "CONFIRMED":
            last_change = route_status.last_state_change or now
            if last_change.tzinfo is None:
                last_change = last_change.replace(tzinfo=timezone.utc)
            dwell_seconds = (now - last_change).total_seconds()
            if dwell_seconds >= 300 and total_count >= 10 and z_score <= 2.0:
                new_state = "RECOVERING"
            else:
                new_state = "CONFIRMED"  # Maintain CONFIRMED until dwell time and sample requirements are met

        elif old_state == "RECOVERING":
            if total_count >= 10 and z_score <= 1.5:
                new_state = "NORMAL"
            elif z_score > 2.5:
                new_state = "CONFIRMED"
            else:
                new_state = "RECOVERING"

        # State 3: SUSPECTED (Evaluated 3rd)
        elif old_state != "CONFIRMED" and old_state != "RECOVERING" and total_count >= 10 and (z_score > 2.0 or (total_count < 20 and failure_rate > 0.20)):
            new_state = "SUSPECTED"

        # State 4: NORMAL (Evaluated 4th)
        elif old_state not in ("CONFIRMED", "RECOVERING"):
            new_state = "NORMAL"

        # Update statistical columns
        route_status.current_failure_rate = failure_rate
        route_status.current_z_score = z_score
        route_status.total_attempts = total_count
        route_status.failed_attempts = failed_count
        route_status.baseline_failure_rate = p0
        route_status.window_start = window_start
        route_status.window_end = now
        route_status.last_evaluated_at = now

        # Handle State Transition Audit Logging
        if new_state != old_state:
            route_status.status = new_state
            route_status.last_state_change = now

            audit = AuditLog(
                case_id=None,
                actor="degradation_detector",
                event="GATEWAY_ROUTE_STATE_CHANGED",
                previous_state=old_state,
                new_state=new_state,
                reason=f"Route ({gw}, {pm}, {b}) state transitioned from {old_state} to {new_state} (Z={z_score:.2f}, Failure Rate={failure_rate * 100:.1f}%, N={total_count}).",
            )
            db.add(audit)
            logger.info(f"Route ({gw}, {pm}, {b}) transitioned {old_state} -> {new_state} (Z={z_score})")

        db.commit()
        db.refresh(route_status)
        return route_status
