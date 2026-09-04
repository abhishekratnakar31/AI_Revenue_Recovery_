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
    """Placeholder handler for refund/dispute creation events."""
    logger.info("Handled refund.created event payload")
