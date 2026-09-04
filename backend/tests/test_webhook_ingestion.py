"""
Milestone 2 Test Suite (Webhook Ingestion)

Tests:
1. HMAC Signature Verification (Valid & Invalid).
2. Endpoint POST /webhooks/razorpay.
3. Atomic Idempotency & Duplicate Handling.
4. Invalid JSON Rejection.
5. Production Mode Signature Enforcement.
6. Async Webhook Processor Execution.
"""

import os
import hmac
import hashlib
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Set test environment
os.environ["USE_TEST_DB"] = "1"
os.environ["TEST_DATABASE_URL"] = "sqlite:///./test.db"

from backend.app.core.config import settings
from backend.app.core.database import Base
from backend.app.main import app
from backend.app.models.models import WebhookEvent
from backend.app.webhooks.verifier import verify_razorpay_signature
from backend.app.webhooks.processor import process_webhook_event

engine = create_engine("sqlite:///./test.db", connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def test_signature_verifier_valid():
    secret = "test_secret_key_123"
    raw_body = b'{"event":"payment.failed","amount":1000}'

    signature = hmac.new(
        key=secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256
    ).hexdigest()

    assert verify_razorpay_signature(raw_body, signature, secret) is True


def test_signature_verifier_invalid():
    secret = "test_secret_key_123"
    raw_body = b'{"event":"payment.failed","amount":1000}'
    bad_signature = "invalid_signature_hash_xyz"

    assert verify_razorpay_signature(raw_body, bad_signature, secret) is False


def test_webhook_post_valid_event():
    client = TestClient(app)
    payload = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test_001",
                    "order_id": "order_test_001",
                    "amount": 50000,
                    "currency": "INR",
                    "status": "failed",
                    "error_reason": "bank_timeout"
                }
            }
        }
    }

    response = client.post(
        "/webhooks/razorpay",
        json=payload,
        headers={
            "X-Razorpay-Event-Id": "evt_test_unique_001",
            "X-Razorpay-Signature": "dummy_sig"
        }
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "received"
    assert data["razorpay_event_id"] == "evt_test_unique_001"
    assert data["event_type"] == "payment.failed"


def test_webhook_atomic_idempotency_duplicate():
    client = TestClient(app)
    payload = {
        "event": "payment.failed",
        "payload": {"payment": {"entity": {"id": "pay_dup_001", "amount": 1000}}}
    }
    headers = {
        "X-Razorpay-Event-Id": "evt_test_duplicate_999",
        "X-Razorpay-Signature": "dummy_sig"
    }

    # 1st Request -> Success
    res1 = client.post("/webhooks/razorpay", json=payload, headers=headers)
    assert res1.status_code == 200
    assert res1.json()["status"] == "received"

    # 2nd Request (Duplicate) -> Atomic Idempotency Ignored
    res2 = client.post("/webhooks/razorpay", json=payload, headers=headers)
    assert res2.status_code == 200
    assert res2.json()["status"] == "duplicate_ignored"


def test_webhook_invalid_json():
    client = TestClient(app)
    response = client.post(
        "/webhooks/razorpay",
        content=b"invalid-non-json-body",
        headers={"Content-Type": "application/json", "X-Razorpay-Event-Id": "evt_bad_json"}
    )
    assert response.status_code in (400, 422)


def test_webhook_signature_rejection_in_prod_mode():
    client = TestClient(app)
    original_env = settings.ENVIRONMENT
    original_secret = settings.RAZORPAY_WEBHOOK_SECRET

    try:
        settings.ENVIRONMENT = "production"
        settings.RAZORPAY_WEBHOOK_SECRET = "real_prod_secret"

        payload = {"event": "payment.failed"}
        response = client.post(
            "/webhooks/razorpay",
            json=payload,
            headers={
                "X-Razorpay-Event-Id": "evt_prod_sig_test",
                "X-Razorpay-Signature": "bad_sig"
            }
        )

        assert response.status_code == 400
        assert "Invalid Razorpay webhook signature" in response.json()["detail"]

    finally:
        settings.ENVIRONMENT = original_env
        settings.RAZORPAY_WEBHOOK_SECRET = original_secret


def test_webhook_processor_execution():
    db = TestingSessionLocal()

    # Create dummy event record
    webhook_rec = WebhookEvent(
        razorpay_event_id="evt_processor_test_01",
        event_type="payment.failed",
        payload_hash="dummy_hash",
        payload={
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_proc_01",
                        "order_id": "order_proc_01",
                        "amount": 25000,
                        "method": "card",
                        "error_reason": "insufficient_funds"
                    }
                }
            }
        },
        processing_status="RECEIVED"
    )
    db.add(webhook_rec)
    db.commit()
    db.refresh(webhook_rec)

    # Process event asynchronously
    process_webhook_event(webhook_rec.id, db)

    db.refresh(webhook_rec)
    assert webhook_rec.processing_status == "PROCESSED"
    db.close()
