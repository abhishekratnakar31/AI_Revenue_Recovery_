import logging
from sqlalchemy.orm import Session
from backend.app.models.models import WebhookEvent

logger = logging.getLogger(__name__)


def process_webhook_event(event_id: int, db: Session):
    """
    Asynchronous worker task that executes processing logic for persisted webhook events.
    """
    webhook_record = db.query(WebhookEvent).filter(WebhookEvent.id == event_id).first()
    if not webhook_record:
        logger.error(f"Webhook record {event_id} not found")
        return

    try:
        event_type = webhook_record.event_type
        payload = webhook_record.payload

        logger.info(f"Processing webhook event: {event_type} (ID: {webhook_record.razorpay_event_id})")

        # Routing by event type
        if event_type == "payment.failed":
            _handle_payment_failed(payload, db)
        elif event_type in ("payment.captured", "payment.authorized"):
            _handle_payment_captured(payload, db)
        elif event_type == "subscription.pending":
            _handle_subscription_pending(payload, db)
        elif event_type == "refund.created":
            _handle_refund_created(payload, db)
        else:
            logger.info(f"Unhandled event type: {event_type}")

        webhook_record.processing_status = "PROCESSED"
        db.commit()

    except Exception as e:
        logger.exception(f"Error processing webhook event {event_id}: {str(e)}")
        webhook_record.processing_status = "FAILED"
        db.commit()


def _handle_payment_failed(payload: dict, db: Session):
    # Placeholders for State Machine integration in Milestone 3
    logger.info("Handled payment.failed event payload")


def _handle_payment_captured(payload: dict, db: Session):
    # Placeholders for Late Capture / Verification integration in Milestone 3
    logger.info("Handled payment.captured event payload")


def _handle_subscription_pending(payload: dict, db: Session):
    logger.info("Handled subscription.pending event payload")


def _handle_refund_created(payload: dict, db: Session):
    logger.info("Handled refund.created event payload")
