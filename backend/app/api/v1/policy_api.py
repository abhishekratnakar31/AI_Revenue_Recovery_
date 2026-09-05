"""
Merchant Guardrail Policy REST Endpoints for RecoverAI API v1.
Implements optimistic concurrency control (atomic SQL UPDATE version check 409),
server-side range validation (422), audit logging, and Bearer token auth.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text

from backend.app.core.database import get_db
from backend.app.schemas.dashboard_schemas import MerchantPolicyResponse, MerchantPolicyUpdateRequest
from backend.app.models.models import MerchantPolicy, AuditLog
from backend.app.api.v1.auth import get_current_merchant_id, require_merchant_auth

router = APIRouter(prefix="/policy", tags=["Merchant Guardrail Policy"])


def _get_or_create_merchant_policy(db: Session, merchant_id: int) -> MerchantPolicy:
    """Fetches or initializes MerchantPolicy record."""
    policy = db.query(MerchantPolicy).filter(MerchantPolicy.merchant_id == merchant_id).first()
    if not policy:
        policy = MerchantPolicy(
            merchant_id=merchant_id,
            max_retries=2,
            minimum_retry_interval=30,
            max_notifications_per_24h=2,
            max_discount_percentage=10.0,
            manual_approval_threshold=25000.0,
            version=1,
        )
        db.add(policy)
        db.commit()
        db.refresh(policy)
    return policy


@router.get("", response_model=MerchantPolicyResponse)
def get_merchant_policy(
    merchant_id: int = Depends(get_current_merchant_id),
    db: Session = Depends(get_db)
):
    """
    Returns current Merchant Policy guardrail settings and version tag.
    """
    policy = _get_or_create_merchant_policy(db, merchant_id)
    return MerchantPolicyResponse(
        id=policy.id,
        merchant_id=policy.merchant_id,
        max_retries=policy.max_retries,
        minimum_retry_interval=policy.minimum_retry_interval,
        max_notifications_per_24h=policy.max_notifications_per_24h,
        max_discount_percentage=float(policy.max_discount_percentage or 10.0),
        manual_approval_threshold=f"{float(policy.manual_approval_threshold or 25000.0):.2f}",
        currency="INR",
        version=policy.version,
        updated_at=policy.updated_at.isoformat() if policy.updated_at else "",
    )


@router.post("", response_model=MerchantPolicyResponse)
def update_merchant_policy(
    payload: MerchantPolicyUpdateRequest,
    merchant_id: int = Depends(require_merchant_auth),
    db: Session = Depends(get_db)
):
    """
    Updates merchant policy guardrails atomically using Optimistic Concurrency Control.
    Requires expected_version in request payload. Returns 409 Conflict if modified concurrently.
    Logs POLICY_UPDATED in AuditLog.
    """
    policy = _get_or_create_merchant_policy(db, merchant_id)

    # Server-Side Range Validation (Pydantic validates fields, extra check here)
    if payload.max_discount_percentage is not None and (payload.max_discount_percentage < 0.0 or payload.max_discount_percentage > 25.0):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="max_discount_percentage must be between 0.0% and 25.0%.",
        )

    prev_state = {
        "max_retries": policy.max_retries,
        "max_discount_percentage": policy.max_discount_percentage,
        "max_notifications_per_24h": policy.max_notifications_per_24h,
        "version": policy.version,
    }

    # Prepare values to update
    new_retries = payload.max_retries if payload.max_retries is not None else policy.max_retries
    new_interval = payload.minimum_retry_interval if payload.minimum_retry_interval is not None else policy.minimum_retry_interval
    new_notifs = payload.max_notifications_per_24h if payload.max_notifications_per_24h is not None else policy.max_notifications_per_24h
    new_disc = payload.max_discount_percentage if payload.max_discount_percentage is not None else policy.max_discount_percentage
    new_thresh = payload.manual_approval_threshold if payload.manual_approval_threshold is not None else policy.manual_approval_threshold

    # Atomic SQL Update with Optimistic Concurrency Version Check
    stmt = (
        db.query(MerchantPolicy)
        .filter(MerchantPolicy.id == policy.id)
        .filter(MerchantPolicy.version == payload.expected_version)
    )

    rows_updated = stmt.update(
        {
            "max_retries": new_retries,
            "minimum_retry_interval": new_interval,
            "max_notifications_per_24h": new_notifs,
            "max_discount_percentage": new_disc,
            "manual_approval_threshold": new_thresh,
            "version": MerchantPolicy.version + 1,
        },
        synchronize_session=False,
    )

    if rows_updated == 0:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Policy version conflict. Expected version {payload.expected_version}, but policy has already been modified.",
        )

    db.commit()

    # Refresh updated policy
    db.refresh(policy)

    # Log Policy Update in AuditLog
    audit = AuditLog(
        case_id=None,
        actor="MERCHANT_ADMIN",
        event="POLICY_UPDATED",
        previous_state=str(prev_state),
        new_state=str({
            "max_retries": policy.max_retries,
            "max_discount_percentage": policy.max_discount_percentage,
            "version": policy.version,
        }),
        reason=f"Updated policy guardrails to v{policy.version}",
    )
    db.add(audit)
    db.commit()

    return MerchantPolicyResponse(
        id=policy.id,
        merchant_id=policy.merchant_id,
        max_retries=policy.max_retries,
        minimum_retry_interval=policy.minimum_retry_interval,
        max_notifications_per_24h=policy.max_notifications_per_24h,
        max_discount_percentage=float(policy.max_discount_percentage or 10.0),
        manual_approval_threshold=f"{float(policy.manual_approval_threshold or 25000.0):.2f}",
        currency="INR",
        version=policy.version,
        updated_at=policy.updated_at.isoformat() if policy.updated_at else "",
    )
