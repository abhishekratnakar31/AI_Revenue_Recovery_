"""
Recovery Case Manager & Attempt Aggregator Module

This module orchestrates entity creation, attempt aggregation, recovery case lifecycles,
and late-capture resolution for payment failures.

Core Business Responsibilities:
1. Entity Lookup/Creation: Manages Customer, Order, Payment, and PaymentAttempt records.
2. Attempt Aggregation: Multiple failed payment attempts for the same order are aggregated under a SINGLE RecoveryCase.
3. Verification Buffer: Failed payments initialize cases in PENDING_VERIFICATION state.
4. Late-Capture Auto-Resolution: If payment.captured arrives while a case is in PENDING_VERIFICATION or RECOVERY_ELIGIBLE,
   automatically transitions the case to AUTO_RESOLVED or RECOVERED and creates an Outcome record (NATURAL_RECOVERY or DIRECT).
5. Buffer Expiration Scanner: `verify_pending_cases_buffer` transitions cases stuck in PENDING_VERIFICATION
   past the buffer timeout (e.g. 5 mins) to RECOVERY_ELIGIBLE.
"""

import datetime
import logging
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from backend.app.models.models import (
    Customer, Order, Payment, PaymentAttempt, RecoveryCase, Outcome, AuditLog
)
from backend.app.state_machine.payment_state import PaymentStateMachine, PaymentStatus, InvalidStateTransitionError

logger = logging.getLogger(__name__)


def utc_now():
    """Returns the current timezone-aware UTC datetime."""
    return datetime.datetime.now(datetime.timezone.utc)


def get_or_create_customer(db: Session, external_id: str, email: str = None) -> Customer:
    """
    Fetches an existing customer profile by external_customer_id, or creates a new one.

    Args:
        db (Session): SQLAlchemy database session.
        external_id (str): Customer identifier string (e.g. cust_123 or email).
        email (str, optional): Customer email address.

    Returns:
        Customer: Database customer model instance.
    """
    customer = db.query(Customer).filter(Customer.external_customer_id == external_id).first()
    if not customer:
        customer = Customer(
            external_customer_id=external_id,
            customer_segment="standard",
            communication_consent=True
        )
        db.add(customer)
        db.commit()
        db.refresh(customer)
    return customer


def get_or_create_order(db: Session, order_id_str: str, customer_id: int, amount: float) -> Order:
    """
    Fetches an existing order record by razorpay_order_id, or creates a new one.

    Args:
        db (Session): SQLAlchemy database session.
        order_id_str (str): Razorpay order ID.
        customer_id (int): Primary key ID of the linked Customer.
        amount (float): Order amount in INR.

    Returns:
        Order: Database order model instance.
    """
    order = db.query(Order).filter(Order.razorpay_order_id == order_id_str).first()
    if not order:
        order = Order(
            razorpay_order_id=order_id_str,
            customer_id=customer_id,
            amount=amount,
            status="created"
        )
        db.add(order)
        db.commit()
        db.refresh(order)
    return order


def get_or_create_payment(db: Session, payment_id_str: str, order_id: int, amount: float, method: str, status: str) -> Payment:
    """
    Fetches or creates a Payment record and updates its current status.

    Args:
        db (Session): SQLAlchemy database session.
        payment_id_str (str): Razorpay payment ID.
        order_id (int): Foreign key ID of linked Order.
        amount (float): Payment amount in INR.
        method (str): Payment method (card, upi, netbanking).
        status (str): Current payment status (failed, captured).

    Returns:
        Payment: Database payment model instance.
    """
    payment = db.query(Payment).filter(Payment.razorpay_payment_id == payment_id_str).first()
    if not payment:
        payment = Payment(
            razorpay_payment_id=payment_id_str,
            order_id=order_id,
            amount=amount,
            payment_method=method,
            status=status
        )
        db.add(payment)
        db.commit()
        db.refresh(payment)
    else:
        payment.status = status
        db.commit()
    return payment


def record_payment_attempt(
    db: Session, payment_id: int, status: str, failure_reason: str = None, gateway: str = None, bank: str = None, method: str = None
) -> PaymentAttempt:
    """
    Records a granular payment attempt linked to a Payment.
    Automatically increments the `attempt_number` counter.

    Args:
        db (Session): Database session.
        payment_id (int): Foreign key ID of Payment.
        status (str): Attempt status (failed, captured).
        failure_reason (str, optional): Gateway/bank error code or description.
        gateway (str, optional): Gateway identifier.
        bank (str, optional): Issuing bank name.
        method (str, optional): Payment method used.

    Returns:
        PaymentAttempt: Created payment attempt database record.
    """
    attempt_count = db.query(PaymentAttempt).filter(PaymentAttempt.payment_id == payment_id).count()
    attempt = PaymentAttempt(
        payment_id=payment_id,
        attempt_number=attempt_count + 1,
        status=status,
        failure_reason=failure_reason,
        gateway=gateway,
        bank=bank,
        payment_method=method
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def process_failed_payment_event(db: Session, payload: Dict[str, Any]) -> RecoveryCase:
    """
    Processes a `payment.failed` webhook payload.

    Workflow:
    1. Parses customer, order, payment, and attempt data from payload.
    2. Aggregates multiple failed attempts under a SINGLE RecoveryCase per order/payment.
    3. Initializes RecoveryCase in PENDING_VERIFICATION status.
    4. Records an AuditLog entry.

    Args:
        db (Session): SQLAlchemy database session.
        payload (dict): Webhook event payload dictionary.

    Returns:
        RecoveryCase: Created or updated RecoveryCase model instance.
    """
    payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
    payment_id_str = payment_entity.get("id", "pay_unknown")
    order_id_str = payment_entity.get("order_id") or f"ord_{payment_id_str}"
    customer_id_str = payment_entity.get("customer_id") or payment_entity.get("email") or f"cust_{payment_id_str}"
    amount = float(payment_entity.get("amount", 0)) / 100.0 if payment_entity.get("amount") else 0.0
    method = payment_entity.get("method", "card")
    error_reason = payment_entity.get("error_reason") or payment_entity.get("error_description") or "payment_failed"
    bank = payment_entity.get("bank")
    gateway = payment_entity.get("acquirer_data", {}).get("bank_transaction_id") or "razorpay"

    # Entities Creation/Lookup
    customer = get_or_create_customer(db, customer_id_str)
    order = get_or_create_order(db, order_id_str, customer.id, amount)
    payment = get_or_create_payment(db, payment_id_str, order.id, amount, method, "failed")
    attempt = record_payment_attempt(db, payment.id, "failed", error_reason, gateway, bank, method)

    # Aggregation: Check if a RecoveryCase already exists for this order or payment
    case = db.query(RecoveryCase).filter(
        (RecoveryCase.order_id == order.id) | (RecoveryCase.payment_id == payment.id)
    ).first()

    if not case:
        case = RecoveryCase(
            case_type="payment_failure",
            customer_id=customer.id,
            order_id=order.id,
            payment_id=payment.id,
            amount_at_risk=amount,
            recoverable_amount_estimate=amount,
            status=PaymentStatus.PENDING_VERIFICATION.value,
            attribution_window=72
        )
        db.add(case)
        db.commit()
        db.refresh(case)

        # Audit Log
        audit = AuditLog(
            case_id=case.id,
            actor="system",
            event="RECOVERY_CASE_CREATED",
            previous_state="UNKNOWN",
            new_state=PaymentStatus.PENDING_VERIFICATION.value,
            reason=f"Payment failed due to {error_reason}"
        )
        db.add(audit)
        db.commit()
    else:
        logger.info(f"Existing RecoveryCase #{case.id} updated with attempt #{attempt.attempt_number}")

    return case


def process_captured_payment_event(db: Session, payload: Dict[str, Any]) -> Optional[RecoveryCase]:
    """
    Processes a `payment.captured` or `payment.authorized` webhook payload.

    Handles Late Capture & Customer Self-Retries:
    1. Updates Payment status to 'captured' and Order status to 'paid'.
    2. Finds matching RecoveryCase.
    3. If case is in PENDING_VERIFICATION (late capture before action):
       Transitions state to AUTO_RESOLVED and sets attribution to NATURAL_RECOVERY.
    4. If case is in RECOVERY_ELIGIBLE or RECOVERY_ACTIVE (captured after recovery action):
       Transitions state to RECOVERED and sets attribution to DIRECT.
    5. Persists gross/net revenue in the Outcome table.

    Args:
        db (Session): SQLAlchemy database session.
        payload (dict): Webhook event payload dictionary.

    Returns:
        Optional[RecoveryCase]: Updated RecoveryCase instance, or None if no matching case exists.
    """
    payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
    payment_id_str = payment_entity.get("id")
    order_id_str = payment_entity.get("order_id")
    amount = float(payment_entity.get("amount", 0)) / 100.0 if payment_entity.get("amount") else 0.0

    # Look up payment and order
    payment = db.query(Payment).filter(Payment.razorpay_payment_id == payment_id_str).first()
    order = db.query(Order).filter(Order.razorpay_order_id == order_id_str).first() if order_id_str else None

    if payment:
        payment.status = "captured"
        payment.captured_at = utc_now()
        db.commit()

    if order:
        order.status = "paid"
        db.commit()

    # Find matching RecoveryCase
    case = None
    if payment:
        case = db.query(RecoveryCase).filter(RecoveryCase.payment_id == payment.id).first()
    if not case and order:
        case = db.query(RecoveryCase).filter(RecoveryCase.order_id == order.id).first()

    if not case:
        logger.info("payment.captured received for order/payment with no active recovery case.")
        return None

    current_status = case.status

    # Late Capture / Self-Retry Resolution Logic
    if current_status in (PaymentStatus.PENDING_VERIFICATION.value, PaymentStatus.FAILED.value):
        target_status = PaymentStatus.AUTO_RESOLVED.value
        attribution = "NATURAL_RECOVERY"
    elif current_status in (PaymentStatus.RECOVERY_ELIGIBLE.value, PaymentStatus.RECOVERY_ACTIVE.value):
        target_status = PaymentStatus.RECOVERED.value
        attribution = "DIRECT"
    else:
        logger.info(f"RecoveryCase #{case.id} already in terminal state {current_status}.")
        return case

    # Perform Validated State Transition
    try:
        new_status = PaymentStateMachine.transition(current_status, target_status)
        case.status = new_status
        case.closed_at = utc_now()
        db.commit()

        # Persist Outcome metrics
        outcome = db.query(Outcome).filter(Outcome.case_id == case.id).first()
        if not outcome:
            outcome = Outcome(
                case_id=case.id,
                intervention="NATURAL_CAPTURE" if attribution == "NATURAL_RECOVERY" else "RECOVERY_ACTION",
                payment_success=True,
                gross_recovered=amount,
                net_recovered=amount,
                attribution_status=attribution,
                recovery_timestamp=utc_now()
            )
            db.add(outcome)
        else:
            outcome.payment_success = True
            outcome.gross_recovered = amount
            outcome.net_recovered = amount - outcome.refund_amount
            outcome.attribution_status = attribution
            outcome.recovery_timestamp = utc_now()
        db.commit()

        # Log Audit Trail
        audit = AuditLog(
            case_id=case.id,
            actor="system",
            event="CASE_AUTO_RESOLVED" if target_status == PaymentStatus.AUTO_RESOLVED.value else "CASE_RECOVERED",
            previous_state=current_status,
            new_state=new_status,
            reason=f"Payment captured ({attribution})"
        )
        db.add(audit)
        db.commit()

    except InvalidStateTransitionError as e:
        logger.warning(f"Failed state transition for case #{case.id}: {str(e)}")

    return case


def verify_pending_cases_buffer(db: Session, max_age_seconds: int = 300) -> int:
    """
    Scans cases stuck in PENDING_VERIFICATION.
    If the buffer window (max_age_seconds) has elapsed without receiving a late payment.captured,
    automatically transitions the case status to RECOVERY_ELIGIBLE.

    Args:
        db (Session): SQLAlchemy database session.
        max_age_seconds (int): Maximum seconds a case stays in PENDING_VERIFICATION. Default is 300 (5 mins).

    Returns:
        int: Total number of cases transitioned to RECOVERY_ELIGIBLE.
    """
    cutoff = utc_now() - datetime.timedelta(seconds=max_age_seconds)
    pending_cases = db.query(RecoveryCase).filter(
        RecoveryCase.status == PaymentStatus.PENDING_VERIFICATION.value,
        RecoveryCase.created_at <= cutoff
    ).all()

    transitioned_count = 0
    for case in pending_cases:
        try:
            new_status = PaymentStateMachine.transition(case.status, PaymentStatus.RECOVERY_ELIGIBLE.value)
            case.status = new_status
            db.commit()

            audit = AuditLog(
                case_id=case.id,
                actor="system",
                event="VERIFICATION_BUFFER_EXPIRED",
                previous_state=PaymentStatus.PENDING_VERIFICATION.value,
                new_state=PaymentStatus.RECOVERY_ELIGIBLE.value,
                reason="Verification buffer window elapsed without late capture."
            )
            db.add(audit)
            db.commit()
            transitioned_count += 1
        except InvalidStateTransitionError as e:
            logger.error(f"Error transitioning case #{case.id}: {str(e)}")

    return transitioned_count
