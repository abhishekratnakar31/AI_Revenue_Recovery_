"""
Razorpay Webhook Signature Verifier Module

This module provides cryptographic signature verification for incoming Razorpay webhooks.

Crucial Architecture Rule:
Razorpay HMAC-SHA256 signatures MUST be verified directly against the raw HTTP request body bytes (`bytes`).
Parsing the request body into JSON or Pydantic models prior to verification causes key-reordering
and whitespace stripping, which breaks HMAC calculations and causes valid webhooks to be incorrectly rejected.
"""

import hmac
import hashlib
from backend.app.core.config import settings


def verify_razorpay_signature(raw_body: bytes, signature: str, secret: str = None) -> bool:
    """
    Verifies the HMAC-SHA256 signature of an incoming Razorpay webhook request.
    
    Args:
        raw_body (bytes): The raw, unparsed byte content of the HTTP request body.
        signature (str): The value of the `X-Razorpay-Signature` header sent by Razorpay.
        secret (str, optional): The webhook secret string. Defaults to settings.RAZORPAY_WEBHOOK_SECRET.
        
    Returns:
        bool: True if the computed HMAC digest matches the provided signature; False otherwise.
        
    Security Features:
        Uses `hmac.compare_digest` to perform constant-time string comparison,
        preventing timing attack vulnerabilities.
    """
    secret_key = secret or settings.RAZORPAY_WEBHOOK_SECRET

    if not signature:
        return False

    # Compute expected HMAC-SHA256 digest on raw request body bytes
    expected_signature = hmac.new(
        key=secret_key.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256
    ).hexdigest()

    # Constant-time comparison to prevent timing attacks
    return hmac.compare_digest(expected_signature, signature)
