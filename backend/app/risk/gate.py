"""
Risk Gate Module

This module evaluates transaction risk and fraud signals prior to recovery intervention.

Risk Evaluation Rules:
1. Fraud/Risk Block: If payment attempt metadata contains fraud flags or fraud_rejection error codes,
   returns decision = BLOCK and transitions case status to POLICY_BLOCKED.
2. High-Value Threshold Check: If transaction amount exceeds merchant `manual_approval_threshold` (e.g. ₹25,000),
   returns decision = REVIEW and flags case status for manual merchant review.
3. Standard Pass: Low-risk transactions return decision = ALLOW.

Every evaluation records a PolicyDecision entry in PostgreSQL for complete auditability.
"""

import logging
from dataclasses import dataclass
from sqlalchemy.orm import Session

from backend.app.models.models import RecoveryCase, PaymentAttempt, MerchantPolicy, PolicyDecision, AuditLog
from backend.app.state_machine.payment_state import PaymentStateMachine, PaymentStatus, InvalidStateTransitionError
from backend.app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class RiskResult:
    """Dataclass holding Risk Gate decision outputs."""
    decision: str  # ALLOW, REVIEW, BLOCK
    risk_score: float  # [0.0 - 1.0]
    reason: str


FRAUD_FAILURE_CODES = {"fraud_rejection", "stolen_card_flag", "risk_decline", "suspected_fraud"}


def evaluate_risk(db: Session, case_id: int) -> RiskResult:
    """
    Evaluates transaction risk for a recovery case.

    Args:
        db (Session): SQLAlchemy database session.
        case_id (int): Primary key ID of RecoveryCase.

    Returns:
        RiskResult: Decision output (ALLOW, REVIEW, or BLOCK).
    """
    case = db.query(RecoveryCase).filter(RecoveryCase.id == case_id).first()
    if not case:
        return RiskResult(decision="BLOCK", risk_score=1.0, reason="Case not found.")

    merchant_policy = db.query(MerchantPolicy).first()
    approval_threshold = merchant_policy.manual_approval_threshold if merchant_policy else settings.DEFAULT_MANUAL_APPROVAL_THRESHOLD

    # 1. Fraud / Risk Flag Check
    recent_attempt = db.query(PaymentAttempt).filter(PaymentAttempt.payment_id == case.payment_id).order_by(PaymentAttempt.attempt_number.desc()).first()
    if recent_attempt and recent_attempt.failure_reason in FRAUD_FAILURE_CODES:
        _record_risk_decision(db, case, "BLOCK", f"Fraud risk flag detected: {recent_attempt.failure_reason}")
        _update_case_status(db, case, PaymentStatus.POLICY_BLOCKED.value, "Risk Gate blocked recovery due to fraud flag.")
        return RiskResult(
            decision="BLOCK",
            risk_score=0.95,
            reason=f"High risk signal: {recent_attempt.failure_reason}"
        )

    # 2. High-Value Transaction Threshold Check (Manual Review)
    if case.amount_at_risk >= approval_threshold:
        reason = f"High-value transaction (₹{case.amount_at_risk:,.2f}) exceeds manual approval threshold (₹{approval_threshold:,.2f})."
        _record_risk_decision(db, case, "REVIEW", reason)
        return RiskResult(
            decision="REVIEW",
            risk_score=0.4,
            reason=reason
        )

    # 3. Standard Low-Risk Pass
    _record_risk_decision(db, case, "ALLOW", "Transaction risk within acceptable limits.")
    return RiskResult(
        decision="ALLOW",
        risk_score=0.1,
        reason="Transaction passed risk evaluation."
    )


def _record_risk_decision(db: Session, case: RecoveryCase, decision: str, reason: str):
    """Records risk evaluation in policy_decisions table."""
    pol_dec = PolicyDecision(
        recovery_case_id=case.id,
        action_type="RISK_GATE_CHECK",
        decision=decision,
        reason=reason,
        policy_version="v1"
    )
    db.add(pol_dec)
    db.commit()


def _update_case_status(db: Session, case: RecoveryCase, target_status: str, reason: str):
    """Internal helper to transition status and record audit log."""
    old_status = case.status
    if old_status == target_status:
        return
    try:
        new_status = PaymentStateMachine.transition(old_status, target_status)
        case.status = new_status
        db.commit()

        audit = AuditLog(
            case_id=case.id,
            actor="system",
            event="RISK_STATUS_UPDATE",
            previous_state=old_status,
            new_state=new_status,
            reason=reason
        )
        db.add(audit)
        db.commit()
    except InvalidStateTransitionError as e:
        logger.warning(f"Risk transition failed for case #{case.id}: {str(e)}")
