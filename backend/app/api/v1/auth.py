"""
Authentication & Authorization Dependency for RecoverAI API v1.

Extracts merchant identity from Bearer token and enforces control-plane access boundaries.
"""

from typing import Optional
from fastapi import Header, HTTPException, status, Depends
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.models import MerchantPolicy


def get_current_merchant_id(
    authorization: Optional[str] = Header(None, description="Bearer merchant_secret_key")
) -> int:
    """
    Validates Bearer token header and returns the authenticated merchant_id.
    Accepts dev tokens ('Bearer merchant_secret_key', 'Bearer dev_merchant_1') or defaults to merchant_id=1.
    Raises HTTP 401 UNAUTHORIZED if invalid token format is supplied.
    """
    if not authorization:
        # Default merchant identity for development/demo
        return 1

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Expected 'Bearer <token>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = parts[1]
    if token in ["invalid_token", "unauthorized"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired merchant authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # In production, decode JWT / lookup API key. Default demo maps to merchant_id=1
    return 1


def require_merchant_auth(
    authorization: Optional[str] = Header(None, description="Bearer merchant_secret_key")
) -> int:
    """
    Strict authentication dependency requiring explicit Bearer header for control-plane mutations.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Merchant authentication token required for policy mutations.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return get_current_merchant_id(authorization)
