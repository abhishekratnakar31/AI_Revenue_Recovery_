import hmac
import hashlib
from fastapi import HTTPException, status
from backend.app.core.config import settings


def verify_razorpay_signature(raw_body: bytes, signature: str, secret: str = None) -> bool:
    """
    Verifies Razorpay HMAC-SHA256 signature against raw request body bytes.
    Crucial: Operates on raw bytes to prevent key-reordering and whitespace modification issues.
    """
    secret_key = secret or settings.RAZORPAY_WEBHOOK_SECRET

    if not signature:
        return False

    expected_signature = hmac.new(
        key=secret_key.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature)
