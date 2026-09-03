"""
Deterministic Policy Engine Module

This module evaluates proposed candidate recovery actions against active merchant policies.

Responsibilities:
1. Rule Orchestration: Executes rule checks for max retries, retry intervals, customer fatigue, and discount caps.
2. Deterministic Execution: Standard Python business logic ensures LLM cannot bypass merchant guardrails.
3. Decision Persistence: Records every evaluation in the `policy_decisions` database table for auditability.
"""

import logging
from dataclasses import dataclass
from sqlalchemy.orm import Session

from backend.app.models.models import RecoveryCase, MerchantPolicy, PolicyDecision, AuditLog
from backend.app.policies.rules import (
    check_max_retries_rule,
    check_retry_interval_rule,
    check_customer_fatigue_rule,
    check_discount_cap_rule
)

logger = logging.getLogger(__name__)


@dataclass
class PolicyResult:
    """Dataclass holding Policy Engine evaluation outputs."""
    decision: str  # ALLOW, BLOCK, REVIEW
    reason: str
    policy_version: str = "v1"


def evaluate_policy(db: Session, case_id: int, action_type: str, proposed_discount: float = 0.0) -> PolicyResult:
    """
    Evaluates a proposed action_type against merchant policies for a given RecoveryCase.

    Args:
        db (Session): SQLAlchemy database session.
        case_id (int): Primary key ID of RecoveryCase.
        action_type (str): Proposed action (RETRY, PAYMENT_LINK, EMAIL_REMINDER, etc.).
        proposed_discount (float, optional): Proposed discount percentage (0.0 - 100.0).

    Returns:
        PolicyResult: Decision object (ALLOW, BLOCK, or REVIEW).
    """
    case = db.query(RecoveryCase).filter(RecoveryCase.id == case_id).first()
    if not case:
        return PolicyResult(decision="BLOCK", reason="Recovery case not found.")

    merchant_policy = db.query(MerchantPolicy).first()

    # Rule Checkers per Action Type
    if action_type in ("RETRY", "DELAYED_RETRY"):
        # 1. Max Retries Check
        passed, reason = check_max_retries_rule(db, case, merchant_policy)
        if not passed:
            _record_policy_decision(db, case.id, action_type, "BLOCK", reason)
            return PolicyResult(decision="BLOCK", reason=reason)

        # 2. Retry Interval Check
        passed, reason = check_retry_interval_rule(db, case, merchant_policy)
        if not passed:
            _record_policy_decision(db, case.id, action_type, "BLOCK", reason)
            return PolicyResult(decision="BLOCK", reason=reason)

    if action_type in ("EMAIL_REMINDER", "PAYMENT_LINK", "SMS_REMINDER", "NOTIFICATION"):
        # 3. Customer Fatigue Check
        passed, reason = check_customer_fatigue_rule(db, case.customer_id, merchant_policy)
        if not passed:
            _record_policy_decision(db, case.id, action_type, "BLOCK", reason)
            return PolicyResult(decision="BLOCK", reason=reason)

    if proposed_discount > 0.0:
        # 4. Discount Cap Check
        passed, reason = check_discount_cap_rule(proposed_discount, merchant_policy)
        if not passed:
            _record_policy_decision(db, case.id, action_type, "BLOCK", reason)
            return PolicyResult(decision="BLOCK", reason=reason)

    # All checks passed -> ALLOW
    reason = f"Action '{action_type}' approved under merchant policy."
    _record_policy_decision(db, case.id, action_type, "ALLOW", reason)
    return PolicyResult(decision="ALLOW", reason=reason)


def _record_policy_decision(db: Session, case_id: int, action_type: str, decision: str, reason: str):
    """Records policy evaluation in policy_decisions table and audit_logs."""
    pol_dec = PolicyDecision(
        recovery_case_id=case_id,
        action_type=action_type,
        decision=decision,
        reason=reason,
        policy_version="v1"
    )
    db.add(pol_dec)

    audit = AuditLog(
        case_id=case_id,
        actor="policy_engine",
        event="POLICY_EVALUATION",
        previous_state=None,
        new_state=decision,
        reason=f"{action_type}: {reason}",
        policy_version="v1"
    )
    db.add(audit)
    db.commit()
