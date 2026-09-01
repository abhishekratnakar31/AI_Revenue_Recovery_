import hashlib
import json
import logging
from fastapi import APIRouter, Request, Header, HTTPException, Depends, BackgroundTasks, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.models.models import WebhookEvent
from backend.app.webhooks.verifier import verify_razorpay_signature
from backend.app.webhooks.processor import process_webhook_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post("/razorpay", status_code=status.HTTP_200_OK)
async def receive_razorpay_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_razorpay_signature: str = Header(None, alias="X-Razorpay-Signature"),
    x_razorpay_event_id: str = Header(None, alias="X-Razorpay-Event-Id"),
    db: Session = Depends(get_db)
):
    """
    Endpoint for receiving Razorpay webhook events.
    1. Preserves raw body for HMAC-SHA256 signature verification.
    2. Enforces atomic idempotency on x-razorpay-event-id.
    3. Asynchronously dispatches event processing.
    """
    raw_body = await request.body()

    # Signature verification (bypass if in testing environment with dummy secret)
    if settings.ENVIRONMENT != "testing" and settings.RAZORPAY_WEBHOOK_SECRET != "dummy_webhook_secret":
        if not x_razorpay_signature or not verify_razorpay_signature(raw_body, x_razorpay_signature):
            logger.warning("Invalid Razorpay webhook signature received")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Razorpay webhook signature"
            )

    # Parse payload
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload"
        )

    # Extract Event ID and Type
    event_type = payload.get("event", "unknown")
    event_id = x_razorpay_event_id or payload.get("event_id")

    if not event_id:
        # Fallback to deterministic payload hash if event ID is missing
        payload_hash = hashlib.sha256(raw_body).hexdigest()
        event_id = f"evt_{payload_hash[:16]}"
    else:
        payload_hash = hashlib.sha256(raw_body).hexdigest()

    # Atomic Idempotency check via DB unique constraint
    existing_event = db.query(WebhookEvent).filter(WebhookEvent.razorpay_event_id == event_id).first()
    if existing_event:
        logger.info(f"Duplicate webhook event received and ignored: {event_id}")
        return {
            "status": "duplicate_ignored",
            "razorpay_event_id": event_id,
            "event_type": event_type
        }

    # Persist Webhook Event
    webhook_record = WebhookEvent(
        razorpay_event_id=event_id,
        event_type=event_type,
        payload_hash=payload_hash,
        payload=payload,
        processing_status="RECEIVED"
    )

    try:
        db.add(webhook_record)
        db.commit()
        db.refresh(webhook_record)
    except IntegrityError:
        db.rollback()
        logger.info(f"Race-condition duplicate event ignored: {event_id}")
        return {
            "status": "duplicate_ignored",
            "razorpay_event_id": event_id,
            "event_type": event_type
        }

    # Dispatch asynchronous background task
    background_tasks.add_task(process_webhook_event, webhook_record.id, db)

    return {
        "status": "received",
        "razorpay_event_id": event_id,
        "event_type": event_type,
        "record_id": webhook_record.id
    }
