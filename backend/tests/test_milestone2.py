import os
import hmac
import hashlib
import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

# Set test environment
os.environ["USE_TEST_DB"] = "1"
os.environ["TEST_DATABASE_URL"] = "sqlite:///./test.db"

from backend.app.core.config import settings
from backend.app.core.database import Base, get_db
from backend.app.models.models import WebhookEvent
from backend.app.main import app
from backend.app.webhooks.verifier import verify_razorpay_signature
from backend.app.webhooks.processor import process_webhook_event

engine = create_engine("sqlite:///./test.db", connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def compute_test_signature(body_bytes: bytes, secret: str = "test_secret") -> str:
    return hmac.new(key=secret.encode("utf-8"), msg=body_bytes, digestmod=hashlib.sha256).hexdigest()


def test_signature_verifier_valid():
    raw_body = b'{"event":"payment.failed","account_id":"acc_123"}'
    secret = "my_secret_key"
    sig = compute_test_signature(raw_body, secret)
    assert verify_razorpay_signature(raw_body, sig, secret) is True


def test_signature_verifier_invalid():
    raw_body = b'{"event":"payment.failed","account_id":"acc_123"}'
    secret = "my_secret_key"
    invalid_sig = "wrong_hash_signature"
    assert verify_razorpay_signature(raw_body, invalid_sig, secret) is False


def test_webhook_post_valid_event():
    client = TestClient(app)
    payload = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_failed_100",
                    "amount": 499900,
                    "currency": "INR",
                    "status": "failed",
                    "error_reason": "bank_technical_error"
                }
            }
        }
    }
    raw_body = json.dumps(payload).encode("utf-8")
    sig = compute_test_signature(raw_body, "dummy_webhook_secret")

    response = client.post(
        "/webhooks/razorpay",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": sig,
            "X-Razorpay-Event-Id": "evt_test_unique_1"
        }
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "received"
    assert data["razorpay_event_id"] == "evt_test_unique_1"
    assert data["event_type"] == "payment.failed"

    # Verify Database Persistence
    db = TestingSessionLocal()
    event_rec = db.query(WebhookEvent).filter_by(razorpay_event_id="evt_test_unique_1").first()
    assert event_rec is not None
    assert event_rec.event_type == "payment.failed"
    assert event_rec.payload["payload"]["payment"]["entity"]["id"] == "pay_failed_100"
    db.close()


def test_webhook_atomic_idempotency_duplicate():
    client = TestClient(app)
    payload = {"event": "payment.failed", "id": "pay_1"}
    raw_body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Razorpay-Event-Id": "evt_idempotent_test_99"
    }

    # First Attempt: Received
    res1 = client.post("/webhooks/razorpay", content=raw_body, headers=headers)
    assert res1.status_code == 200
    assert res1.json()["status"] == "received"

    # Second Attempt (Duplicate): Ignored
    res2 = client.post("/webhooks/razorpay", content=raw_body, headers=headers)
    assert res2.status_code == 200
    assert res2.json()["status"] == "duplicate_ignored"

    # Verify only 1 record exists in DB
    db = TestingSessionLocal()
    count = db.query(WebhookEvent).filter_by(razorpay_event_id="evt_idempotent_test_99").count()
    assert count == 1
    db.close()


def test_webhook_invalid_json():
    client = TestClient(app)
    response = client.post(
        "/webhooks/razorpay",
        content=b"invalid-non-json-body",
        headers={"Content-Type": "application/json", "X-Razorpay-Event-Id": "evt_bad_json"}
    )
    assert response.status_code == 400
    assert "Invalid JSON payload" in response.json()["detail"]


def test_webhook_signature_rejection_in_prod_mode(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", "prod_secret_123")

    client = TestClient(app)
    payload = {"event": "payment.failed"}
    raw_body = json.dumps(payload).encode("utf-8")

    # Wrong signature
    response = client.post(
        "/webhooks/razorpay",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": "invalid_sig_hash",
            "X-Razorpay-Event-Id": "evt_prod_test"
        }
    )
    assert response.status_code == 400
    assert "Invalid Razorpay webhook signature" in response.json()["detail"]


def test_webhook_processor_execution():
    db = TestingSessionLocal()
    event_rec = WebhookEvent(
        razorpay_event_id="evt_proc_test_01",
        event_type="payment.failed",
        payload_hash="hash01",
        payload={"event": "payment.failed"},
        processing_status="RECEIVED"
    )
    db.add(event_rec)
    db.commit()
    db.refresh(event_rec)

    # Process webhook
    process_webhook_event(event_rec.id, db)

    db.refresh(event_rec)
    assert event_rec.processing_status == "PROCESSED"
    db.close()
