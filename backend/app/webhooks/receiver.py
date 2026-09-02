"""
Razorpay Webhook Receiver API Module

This module exposes the `POST /webhooks/razorpay` endpoint for receiving payment events from Razorpay.

Architectural Workflow & Resilience:
1. Signature Verification: Preserves raw request body bytes to verify HMAC-SHA256 signatures reliably.
2. Atomic Idempotency: Uses database-level unique constraints (`UNIQUE(razorpay_event_id)`) to instantly
   drop duplicate webhook retries and return `{"status": "duplicate_ignored"}` without re-executing business logic.
3. Asynchronous Dispatch: Dispatches heavy background tasks via FastAPI `BackgroundTasks` so the endpoint
   returns an HTTP 200 response instantly without blocking the payment gateway.
"""

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

# FastAPI Router for webhook endpoints
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
    Receives and ingests incoming Razorpay webhook event payloads.
    
    Processing Steps:
    1. Reads raw HTTP request bytes (`await request.body()`) to preserve payload integrity.
    2. Validates `X-Razorpay-Signature` against `RAZORPAY_WEBHOOK_SECRET` (bypassed in testing mode).
    3. Parses JSON payload and extracts event type (e.g. `payment.failed`, `payment.captured`) and unique event ID.
    4. Computes SHA-256 hash of payload bytes.
    5. Attempts atomic DB insert into `webhook_events`. If duplicate `x_razorpay_event_id` exists,
       catches `IntegrityError` and returns `{"status": "duplicate_ignored"}` instantly.
    6. If event is new, dispatches `process_webhook_event` background task and returns `{"status": "received"}`.
    
    Args:
        request (Request): FastAPI request object for reading raw body.
        background_tasks (BackgroundTasks): FastAPI task queue for async processing.
        x_razorpay_signature (str): Razorpay HMAC signature header.
        x_razorpay_event_id (str): Razorpay unique event ID header.
        db (Session): Database session dependency.
        
    Returns:
        dict: JSON response object containing status ("received" or "duplicate_ignored") and metadata.
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
        # Fallback to deterministic payload hash if header event ID is missing
        payload_hash = hashlib.sha256(raw_body).hexdigest()
        event_id = f"evt_{payload_hash[:16]}"
    else:
        payload_hash = hashlib.sha256(raw_body).hexdigest()

    # Atomic Idempotency check via DB query check
    existing_event = db.query(WebhookEvent).filter(WebhookEvent.razorpay_event_id == event_id).first()
    if existing_event:
        logger.info(f"Duplicate webhook event received and ignored: {event_id}")
        return {
            "status": "duplicate_ignored",
            "razorpay_event_id": event_id,
            "event_type": event_type
        }

    # Persist Webhook Event in PostgreSQL
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
        # Catch race condition duplicates occurring between check and insert
        db.rollback()
        logger.info(f"Race-condition duplicate event ignored: {event_id}")
        return {
            "status": "duplicate_ignored",
            "razorpay_event_id": event_id,
            "event_type": event_type
        }

    # Dispatch asynchronous background worker task
    background_tasks.add_task(process_webhook_event, webhook_record.id, db)

    return {
        "status": "received",
        "razorpay_event_id": event_id,
        "event_type": event_type,
        "record_id": webhook_record.id
    }
