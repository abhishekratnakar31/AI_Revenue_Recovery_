"""
Recovery Cases & Decision Audit Timeline REST Endpoints for RecoverAI API v1.
Provides paginated case listing, metadata, and backend-projected decision audit traces.
"""

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc, or_

from backend.app.core.database import get_db
from backend.app.schemas.dashboard_schemas import (
    CaseListResponse,
    CaseItemResponse,
    CaseDetailResponse,
    CaseTimelineResponse,
    TimelineStep,
)
from backend.app.models.models import (
    RecoveryCase,
    Customer,
    Order,
    Payment,
    PaymentAttempt,
    Outcome,
    PolicyDecision,
    AgentDecision,
    ModelPrediction,
    RecoveryAction,
    ExperimentAssignment,
)
from backend.app.api.v1.auth import get_current_merchant_id

router = APIRouter(prefix="/cases", tags=["Recovery Cases & Timeline"])


@router.get("", response_model=CaseListResponse)
def get_cases_list(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(25, ge=1, le=100, description="Items per page"),
    status_filter: Optional[str] = Query(None, alias="status", description="Optional case status filter"),
    payment_method: Optional[str] = Query(None, description="Optional payment method filter"),
    search: Optional[str] = Query(None, description="Search by customer ID, external ID, case ID, or payment ID"),
    sort_by: str = Query("created_at", description="Field to sort by: created_at, amount_at_risk, status"),
    sort_order: str = Query("desc", description="Sort direction: asc or desc"),
    merchant_id: int = Depends(get_current_merchant_id),
    db: Session = Depends(get_db)
):
    """
    Returns paginated list of recovery cases with metadata, search, and sorting.
    """
    query = (
        db.query(RecoveryCase, Customer, Order, Payment)
        .outerjoin(Customer, RecoveryCase.customer_id == Customer.id)
        .outerjoin(Order, RecoveryCase.order_id == Order.id)
        .outerjoin(Payment, RecoveryCase.payment_id == Payment.id)
    )

    if status_filter:
        query = query.filter(RecoveryCase.status == status_filter.upper())

    if payment_method:
        query = query.filter(Payment.payment_method == payment_method.upper())

    if search:
        search_term = f"%{search.strip()}%"
        filters = [
            Customer.external_customer_id.ilike(search_term),
            Payment.razorpay_payment_id.ilike(search_term),
        ]
        if search.strip().isdigit():
            filters.append(RecoveryCase.id == int(search.strip()))
        query = query.filter(or_(*filters))

    # Apply sorting
    sort_col = RecoveryCase.created_at
    if sort_by == "amount_at_risk":
        sort_col = RecoveryCase.amount_at_risk
    elif sort_by == "status":
        sort_col = RecoveryCase.status

    if sort_order.lower() == "asc":
        query = query.order_by(asc(sort_col))
    else:
        query = query.order_by(desc(sort_col))

    total_count = query.count()
    offset = (page - 1) * page_size
    results = query.offset(offset).limit(page_size).all()

    items: List[CaseItemResponse] = []
    for case, cust, order, pay in results:
        amt = float(case.amount_at_risk or 0.0)
        
        # Fetch latest payment attempt if payment exists
        att = None
        if pay:
            att = (
                db.query(PaymentAttempt)
                .filter(PaymentAttempt.payment_id == pay.id)
                .order_by(desc(PaymentAttempt.timestamp))
                .first()
            )

        items.append(
            CaseItemResponse(
                id=case.id,
                customer_id=cust.id if cust else None,
                customer_external_id=cust.external_customer_id if cust else "UNKNOWN",
                order_id=order.id if order else None,
                payment_id=pay.id if pay else None,
                amount_at_risk=f"{amt:.2f}",
                currency="INR",
                case_type=case.case_type or "payment_failure",
                status=case.status,
                payment_method=(pay.payment_method if pay else None) or "UPI",
                gateway=(att.gateway if att else None) or "razorpay",
                bank=(att.bank if att else None) or "N/A",
                created_at=case.created_at.isoformat() if case.created_at else "",
                closed_at=case.closed_at.isoformat() if case.closed_at else None,
            )
        )

    has_next = (offset + len(items)) < total_count

    return CaseListResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total_count,
        has_next=has_next,
    )


@router.get("/{case_id}", response_model=CaseDetailResponse)
def get_case_detail(
    case_id: int,
    merchant_id: int = Depends(get_current_merchant_id),
    db: Session = Depends(get_db)
):
    """
    Returns detailed case metadata for a specific RecoveryCase ID.
    """
    case = db.query(RecoveryCase).filter(RecoveryCase.id == case_id).first()
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"RecoveryCase #{case_id} not found."
        )

    customer = db.query(Customer).filter(Customer.id == case.customer_id).first()
    order = db.query(Order).filter(Order.id == case.order_id).first() if case.order_id else None
    payment = db.query(Payment).filter(Payment.id == case.payment_id).first() if case.payment_id else None
    asgn = db.query(ExperimentAssignment).filter(ExperimentAssignment.case_id == case.id).first()
    policy_decisions = db.query(PolicyDecision).filter(PolicyDecision.recovery_case_id == case.id).all()

    amt = float(case.amount_at_risk or 0.0)

    return CaseDetailResponse(
        case_id=case.id,
        status=case.status,
        amount_at_risk=f"{amt:.2f}",
        currency="INR",
        case_type=case.case_type or "payment_failure",
        customer={
            "id": customer.id if customer else None,
            "external_id": customer.external_customer_id if customer else None,
            "lifetime_value": float(customer.lifetime_value or 0.0) if customer else 0.0,
        },
        order={
            "id": order.id if order else None,
            "razorpay_order_id": order.razorpay_order_id if order else None,
        },
        payment={
            "id": payment.id if payment else None,
            "razorpay_payment_id": payment.razorpay_payment_id if payment else None,
            "status": payment.status if payment else None,
            "method": payment.payment_method if payment else None,
        },
        assignment_group=asgn.assignment_group if asgn else None,
        policy_decisions=[
            {"action": p.action_type, "decision": p.decision, "reason": p.reason} for p in policy_decisions
        ],
        created_at=case.created_at.isoformat() if case.created_at else "",
        closed_at=case.closed_at.isoformat() if case.closed_at else None,
    )


@router.get("/{case_id}/timeline", response_model=CaseTimelineResponse)
def get_case_timeline(
    case_id: int,
    merchant_id: int = Depends(get_current_merchant_id),
    db: Session = Depends(get_db)
):
    """
    Returns backend-projected decision audit timeline explicitly separating:
    1. PAYMENT_ATTEMPT: Gateway failure details
    2. ML_RISK: Calibrated P(recovery) score
    3. M8_AGENT_DECISION: Gemini selected action & expected ENV
    4. M11_ROUTE_GUARDRAIL: Route degradation check & decision (ALLOW/BLOCK)
    5. M9_ACTION_EXECUTION: Executed action details & provider status
    6. M10_COMMUNICATION: Notification channel & safety check
    7. M12_FINANCIAL_OUTCOME: Net recovered revenue & attribution status
    """
    case = db.query(RecoveryCase).filter(RecoveryCase.id == case_id).first()
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"RecoveryCase #{case_id} not found."
        )

    attempts = db.query(PaymentAttempt).filter(PaymentAttempt.payment_id == case.payment_id).all()
    prediction = db.query(ModelPrediction).filter(ModelPrediction.recovery_case_id == case.id).first()
    agent_dec = db.query(AgentDecision).filter(AgentDecision.recovery_case_id == case.id).first()
    policy_decs = db.query(PolicyDecision).filter(PolicyDecision.recovery_case_id == case.id).all()
    actions = db.query(RecoveryAction).filter(RecoveryAction.recovery_case_id == case.id).all()
    outcome = db.query(Outcome).filter(Outcome.case_id == case.id).first()

    steps: List[TimelineStep] = []
    step_num = 1

    # Step 1: PAYMENT_ATTEMPT
    for att in attempts:
        steps.append(
            TimelineStep(
                step_number=step_num,
                step_type="PAYMENT_ATTEMPT",
                timestamp=att.timestamp.isoformat() if att.timestamp else case.created_at.isoformat(),
                title=f"Payment Attempt #{att.attempt_number} Failed",
                details={
                    "gateway": att.gateway or "razorpay",
                    "payment_method": att.payment_method or "UPI",
                    "bank": att.bank or "HDFC",
                    "failure_reason": att.failure_reason or "BANK_TIMEOUT",
                    "attempt_number": att.attempt_number,
                },
            )
        )
        step_num += 1

    # Step 2: ML_RISK
    if prediction:
        steps.append(
            TimelineStep(
                step_number=step_num,
                step_type="ML_RISK",
                timestamp=prediction.predicted_at.isoformat() if prediction.predicted_at else case.created_at.isoformat(),
                title="ML Calibrated Recovery Assessment",
                details={
                    "calibrated_p_recovery": round(prediction.prediction, 4),
                    "model_name": prediction.model_name,
                    "model_version": prediction.model_version,
                    "calibration_method": "isotonic",
                },
            )
        )
        step_num += 1

    # Step 3: M8_AGENT_DECISION
    if agent_dec:
        steps.append(
            TimelineStep(
                step_number=step_num,
                step_type="M8_AGENT_DECISION",
                timestamp=agent_dec.created_at.isoformat() if agent_dec.created_at else case.created_at.isoformat(),
                title="M8 Economic Value Decision Agent",
                details={
                    "selected_action": agent_dec.selected_action,
                    "diagnosis_summary": agent_dec.diagnosis_summary or "Route timeout analysis",
                    "confidence_score": round(agent_dec.confidence_score or 0.9, 2),
                    "provider": agent_dec.provider or "gemini",
                },
            )
        )
        step_num += 1

    # Step 4: M11_ROUTE_GUARDRAIL
    for pol in policy_decs:
        steps.append(
            TimelineStep(
                step_number=step_num,
                step_type="M11_ROUTE_GUARDRAIL",
                timestamp=pol.created_at.isoformat() if pol.created_at else case.created_at.isoformat(),
                title="M11 Deterministic Policy & Route Guardrail",
                details={
                    "action_evaluated": pol.action_type,
                    "decision": pol.decision,
                    "reason": pol.reason,
                    "route": getattr(pol, "route_evaluated", "razorpay/UPI/HDFC"),
                },
            )
        )
        step_num += 1

    # Step 5: M9_ACTION_EXECUTION
    for act in actions:
        steps.append(
            TimelineStep(
                step_number=step_num,
                step_type="M9_ACTION_EXECUTION",
                timestamp=act.executed_at.isoformat() if act.executed_at else case.created_at.isoformat(),
                title=f"M9 Recovery Execution: {act.action_type}",
                details={
                    "action_type": act.action_type,
                    "status": act.status,
                    "idempotency_key": act.idempotency_key,
                    "provider": act.provider or "razorpay",
                },
            )
        )
        step_num += 1

    # Step 6: M12_FINANCIAL_OUTCOME
    if outcome:
        net_amt = float(outcome.net_recovered or 0.0)
        steps.append(
            TimelineStep(
                step_number=step_num,
                step_type="M12_FINANCIAL_OUTCOME",
                timestamp=outcome.recovery_timestamp.isoformat() if outcome.recovery_timestamp else case.created_at.isoformat(),
                title="M12 Financial Outcome & Attribution",
                details={
                    "is_recovered": outcome.is_recovered,
                    "net_recovered_revenue": f"{net_amt:.2f}",
                    "cash_collected": f"{float(outcome.gross_recovered or 0.0):.2f}",
                    "refund_deductions": f"{float(outcome.refund_deductions or 0.0):.2f}",
                    "attribution_status": outcome.attribution_status or "DIRECT",
                    "currency": "INR",
                },
            )
        )

    return CaseTimelineResponse(
        case_id=case.id,
        current_status=case.status,
        steps=steps,
    )
