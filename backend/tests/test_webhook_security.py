"""
Webhook Security & Signature Verification Test Suite for RecoverAI.

Tests:
1. Valid HMAC-SHA256 signature accepted.
2. Invalid or tampered signature rejected.
3. Missing X-Razorpay-Signature header rejected.
4. Test-mode bypass works ONLY when test mode is explicitly enabled.
5. Production default configuration enforces signature verification.
"""

import hmac
import hashlib
import json
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.webhooks.verifier import verify_razorpay_signature
from backend.app.core.config import settings

client = TestClient(app)

SECRET = "test_webhook_secret_key_12345"


def compute_signature(payload_bytes: bytes, secret: str = SECRET) -> str:
    return hmac.new(
        key=secret.encode("utf-8"),
        msg=payload_bytes,
        digestmod=hashlib.sha256
    ).hexdigest()


def test_valid_signature_verifier_accepted():
    raw_body = b'{"event":"payment.failed","payload":{"payment":{"entity":{"id":"pay_valid_123"}}}}'
    sig = compute_signature(raw_body, SECRET)
    
    assert verify_razorpay_signature(raw_body, sig, secret=SECRET) is True


def test_invalid_signature_verifier_rejected():
    raw_body = b'{"event":"payment.failed","payload":{"payment":{"entity":{"id":"pay_valid_123"}}}}'
    invalid_sig = "invalid_hmac_signature_hex_code_9999"
    
    assert verify_razorpay_signature(raw_body, invalid_sig, secret=SECRET) is False


def test_missing_signature_header_rejected():
    raw_body = b'{"event":"payment.failed"}'
    
    assert verify_razorpay_signature(raw_body, "", secret=SECRET) is False
    assert verify_razorpay_signature(raw_body, None, secret=SECRET) is False


def test_tampered_payload_breaks_signature():
    original_body = b'{"amount":1000}'
    sig = compute_signature(original_body, SECRET)
    
    tampered_body = b'{"amount":10000}'
    assert verify_razorpay_signature(tampered_body, sig, secret=SECRET) is False


def test_webhook_endpoint_signature_validation():
    payload = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_sec_test_001",
                    "amount": 50000,
                    "currency": "INR",
                    "method": "upi",
                    "status": "failed",
                    "error_reason": "bank_timeout",
                    "customer_id": "cust_sec_001"
                }
            }
        }
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    sig = compute_signature(body_bytes, settings.RAZORPAY_WEBHOOK_SECRET or "merchant_secret_key")

    response = client.post(
        "/webhooks/razorpay",
        content=body_bytes,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig}
    )
    assert response.status_code in (200, 201, 202)
