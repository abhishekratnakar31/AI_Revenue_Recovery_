"""
Recovery Eligibility Engine Module

This module determines whether a recovery case can legally and technically enter the recovery pipeline.

Eligibility Checks:
1. Customer Opt-Out: If customer.opt_out == True, transitions status to CUSTOMER_OPTED_OUT.
2. Case Status Check: Excludes already resolved (AUTO_RESOLVED, RECOVERED) or closed cases.
3. Case Expiration Check: Excludes cases older than attribution_window (e.g. > 72 hours).
4. Permanent Failure Check: Excludes unrecoverable failures (e.g. card stolen, account closed).
5. Max Retries Check: Excludes cases where payment attempt count >= merchant max_retries.

If eligible, transitions cases in PENDING_VERIFICATION to RECOVERY_ELIGIBLE.
"""

import datetime
import logging
from dataclasses import dataclass
from sqlalchemy.orm import Session

from backend.app.models.models import Customer, PaymentAttempt, RecoveryCase, MerchantPolicy, AuditLog
from backend.app.state_machine.payment_state import PaymentStateMachine, PaymentStatus, InvalidStateTransitionError
from backend.app.core.config import settings

logger = logging.getLogger(__name__)


def utc_now() -> datetime.datetime:
    """Returns timezone-aware UTC datetime."""
    return datetime.datetime.now(datetime.timezone.utc)


def ensure_utc(dt: datetime.datetime) -> datetime.datetime:
    """
    Ensures a datetime object is timezone-aware UTC.
    Converts naive datetimes (common in SQLite test mode) to UTC aware datetimes.
    """
    if dt is None:
        return utc_now()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


@dataclass
class EligibilityResult:
    """Dataclass holding eligibility evaluation results."""
    is_eligible: bool
    status: str
    reason: str


# Failure reasons classified as permanently unrecoverable
PERMANENT_FAILURE_REASONS = {
    "card_stolen",
    "account_closed",
    "invalid_account",
    "fraud_blocked",
    "stolen_card",
    "customer_cancelled_permanently"
}


def evaluate_eligibility(db: Session, case_id: int) -> EligibilityResult:
    """
    Evaluates whether a RecoveryCase is eligible to enter active recovery pipelines.
    """
    case = db.query(RecoveryCase).filter(RecoveryCase.id == case_id).first()
    if not case:
        return EligibilityResult(is_eligible=False, status="NOT_FOUND", reason="Recovery case not found.")

    customer = db.query(Customer).filter(Customer.id == case.customer_id).first()
    merchant_policy = db.query(MerchantPolicy).first()
    max_retries = merchant_policy.max_retries if merchant_policy else settings.DEFAULT_MAX_RETRIES

    # 1. Customer Opt-Out Check
    if customer and customer.opt_out:
        _update_case_status(db, case, PaymentStatus.CUSTOMER_OPTED_OUT.value, "Customer has opted out of recovery communications.")
        return EligibilityResult(
            is_eligible=False,
            status=PaymentStatus.CUSTOMER_OPTED_OUT.value,
            reason="Customer opted out of recovery communications."
        )

    # 2. Already Resolved / Terminal State Check
    if case.status in (PaymentStatus.AUTO_RESOLVED.value, PaymentStatus.RECOVERED.value, PaymentStatus.FAILED_PERMANENTLY.value):
        return EligibilityResult(
            is_eligible=False,
            status=case.status,
            reason=f"Case is already in terminal state '{case.status}'."
        )

    # 3. Case Expiration Check (Attribution Window Exceeded)
    case_created_at = ensure_utc(case.created_at)
    case_age_hours = (utc_now() - case_created_at).total_seconds() / 3600.0

    if case_age_hours > case.attribution_window:
        _update_case_status(db, case, PaymentStatus.EXPIRED.value, f"Case age ({case_age_hours:.1f}h) exceeded attribution window ({case.attribution_window}h).")
        return EligibilityResult(
            is_eligible=False,
            status=PaymentStatus.EXPIRED.value,
            reason=f"Case age exceeded attribution window of {case.attribution_window} hours."
        )

    # 4. Permanent Failure Check
    recent_attempt = db.query(PaymentAttempt).filter(PaymentAttempt.payment_id == case.payment_id).order_by(PaymentAttempt.attempt_number.desc()).first()
    if recent_attempt and recent_attempt.failure_reason in PERMANENT_FAILURE_REASONS:
        _update_case_status(db, case, PaymentStatus.FAILED_PERMANENTLY.value, f"Permanent failure reason: {recent_attempt.failure_reason}")
        return EligibilityResult(
            is_eligible=False,
            status=PaymentStatus.FAILED_PERMANENTLY.value,
            reason=f"Unrecoverable failure reason '{recent_attempt.failure_reason}'."
        )

    # 5. Max Retries Limit Check
    attempt_count = db.query(PaymentAttempt).filter(PaymentAttempt.payment_id == case.payment_id).count() if case.payment_id else 1
    if attempt_count >= max_retries:
        _update_case_status(db, case, PaymentStatus.MAX_RETRIES_REACHED.value, f"Attempt count ({attempt_count}) reached merchant limit ({max_retries}).")
        return EligibilityResult(
            is_eligible=False,
            status=PaymentStatus.MAX_RETRIES_REACHED.value,
            reason=f"Maximum retry attempt limit of {max_retries} reached."
        )

    # 6. Eligible: Transition PENDING_VERIFICATION -> RECOVERY_ELIGIBLE
    if case.status == PaymentStatus.PENDING_VERIFICATION.value:
        _update_case_status(db, case, PaymentStatus.RECOVERY_ELIGIBLE.value, "Passed all eligibility checks.")

    return EligibilityResult(
        is_eligible=True,
        status=case.status,
        reason="Case passed all eligibility checks."
    )


def _update_case_status(db: Session, case: RecoveryCase, target_status: str, reason: str):
    """Internal helper to transition status and record audit log."""
    old_status = case.status
    if old_status == target_status:
        return
    try:
        new_status = PaymentStateMachine.transition(old_status, target_status)
        case.status = new_status
        if new_status in (PaymentStatus.EXPIRED.value, PaymentStatus.FAILED_PERMANENTLY.value, PaymentStatus.CUSTOMER_OPTED_OUT.value, PaymentStatus.MAX_RETRIES_REACHED.value):
            case.closed_at = utc_now()
        db.commit()

        audit = AuditLog(
            case_id=case.id,
            actor="system",
            event="ELIGIBILITY_STATUS_UPDATE",
            previous_state=old_status,
            new_state=new_status,
            reason=reason
        )
        db.add(audit)
        db.commit()
    except InvalidStateTransitionError as e:
        logger.warning(f"Eligibility transition failed for case #{case.id}: {str(e)}")
