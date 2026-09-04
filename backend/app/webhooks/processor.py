"""
Asynchronous Webhook Processor Module

This module defines background worker functions that process persisted webhook events asynchronously.

Workflow:
1. Receives `event_id` (primary key of `webhook_events` record).
2. Manages its own database session lifecycle (SessionLocal) independently of HTTP request lifecycles.
3. Looks up the stored event payload and event type.
4. Routes the payload to the corresponding specialized handler (_handle_payment_failed, _handle_payment_captured, etc.).
5. Updates `processing_status` in the `webhook_events` table to `PROCESSED` (or `FAILED` if an exception occurs).
"""

import logging
from typing import Optional
from sqlalchemy.orm import Session

from backend.app.core.database import SessionLocal
from backend.app.models.models import WebhookEvent
from backend.app.recovery.case_manager import (
    process_failed_payment_event,
    process_captured_payment_event
)

logger = logging.getLogger(__name__)


def process_webhook_event(event_id: int, db: Optional[Session] = None):
    """
    Asynchronous worker task that executes processing routines for a persisted webhook event.
    
    Args:
        event_id (int): Primary key ID of the `WebhookEvent` database record.
        db (Optional[Session]): Optional database session instance. If None, creates a fresh SessionLocal session.
        
    Behavior:
        - Manages its own independent session lifecycle to prevent closed-session bugs in FastAPI background tasks.
        - Updates processing_status to 'PROCESSED' on success.
        - Updates processing_status to 'FAILED' on unhandled exceptions.
    """
    # Create an independent session if none provided (e.g. when called from BackgroundTasks)
    close_session_on_exit = False
    if db is None:
        db = SessionLocal()
        close_session_on_exit = True

    try:
        webhook_record = db.query(WebhookEvent).filter(WebhookEvent.id == event_id).first()
        if not webhook_record:
            logger.error(f"Webhook record {event_id} not found in database.")
            return

        event_type = webhook_record.event_type
        payload = webhook_record.payload

        logger.info(f"Processing webhook event: {event_type} (ID: {webhook_record.razorpay_event_id})")

        # Route event to dedicated handlers
        if event_type == "payment.failed":
            _handle_payment_failed(payload, db)
        elif event_type in ("payment.captured", "payment.authorized"):
            _handle_payment_captured(payload, db)
        elif event_type == "subscription.pending":
            _handle_subscription_pending(payload, db)
        elif event_type == "refund.created":
            _handle_refund_created(payload, db)
        else:
            logger.info(f"Unhandled event type received: {event_type}")

        # Update status on success
        webhook_record.processing_status = "PROCESSED"
        db.commit()

    except Exception as e:
        logger.exception(f"Error processing webhook event ID {event_id}: {str(e)}")
        if webhook_record:
            webhook_record.processing_status = "FAILED"
            db.commit()
    finally:
        if close_session_on_exit and db:
            db.close()


def _handle_payment_failed(payload: dict, db: Session):
    """
    Handles `payment.failed` webhook payload.
    Triggers Recovery Case creation/update and initializes status to PENDING_VERIFICATION.
    """
    case = process_failed_payment_event(db, payload)
    logger.info(f"Handled payment.failed event payload -> RecoveryCase #{case.id} (Status: {case.status})")


def _handle_payment_captured(payload: dict, db: Session):
    """
    Handles `payment.captured` or `payment.authorized` webhook payload.
    Resolves active recovery cases (moves PENDING_VERIFICATION to AUTO_RESOLVED or RECOVERY_ACTIVE to RECOVERED).
    """
    case = process_captured_payment_event(db, payload)
    if case:
        logger.info(f"Handled payment.captured event payload -> RecoveryCase #{case.id} resolved (Status: {case.status})")
    else:
        logger.info("Handled payment.captured event payload with no existing recovery case.")


def _handle_subscription_pending(payload: dict, db: Session):
    """Placeholder handler for subscription renewal failure events."""
    logger.info("Handled subscription.pending event payload")


def _handle_refund_created(payload: dict, db: Session):
    """
    Handles `refund.created` webhook payload.
    Extracts razorpay_refund_id, payment_id, amount and delegates to AttributionEngine.process_refund_deduction().
    """
    from backend.app.analytics.attribution import AttributionEngine
    from backend.app.models.models import Payment

    refund_entity = payload.get("payload", {}).get("refund", {}).get("entity", {}) if "payload" in payload else payload.get("entity", payload)

    razorpay_refund_id = refund_entity.get("id") or payload.get("razorpay_refund_id") or payload.get("id")
    payment_id_str = refund_entity.get("payment_id") or payload.get("payment_id")
    amount_raw = refund_entity.get("amount", 0) or payload.get("amount", 0)

    # Razorpay amounts in webhooks are typically in paise (e.g. 50000 paise = 500 INR)
    if isinstance(amount_raw, int) and amount_raw >= 100 and ("notes" in refund_entity or "entity" in payload):
        refund_amount = amount_raw / 100.0
    else:
        refund_amount = float(amount_raw)

    if not razorpay_refund_id:
        logger.warning("refund.created payload missing razorpay_refund_id.")
        return

    # Resolve internal Payment ID
    payment_db_id = None
    if isinstance(payment_id_str, int):
        payment_db_id = payment_id_str
    elif isinstance(payment_id_str, str):
        p = db.query(Payment).filter(Payment.razorpay_payment_id == payment_id_str).first()
        if p:
            payment_db_id = p.id
        elif payment_id_str.isdigit():
            payment_db_id = int(payment_id_str)

    if not payment_db_id:
        logger.warning(f"Could not resolve internal payment ID for refund '{razorpay_refund_id}' (payment_id: {payment_id_str})")
        return

    res = AttributionEngine.process_refund_deduction(
        db=db,
        razorpay_refund_id=razorpay_refund_id,
        payment_id=payment_db_id,
        refund_amount=refund_amount,
    )
    logger.info(f"Handled refund.created event '{razorpay_refund_id}' -> {res}")

