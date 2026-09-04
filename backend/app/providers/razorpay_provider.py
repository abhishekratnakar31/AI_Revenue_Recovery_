"""Razorpay Payment Provider module for RecoverAI live/staging gateway integration.

Interfaces with Razorpay Payment Links API and Payment Retry APIs using HTTP REST requests.
Uses official HTTP header `X-Razorpay-Idempotency-Key` or payload `reference_id`.
"""

import os
import json
import time
import base64
import urllib.request
import urllib.error
from decimal import Decimal
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta

from backend.app.providers.base import PaymentProvider, ProviderResponse, PaymentLinkResponse


class RazorpayPaymentProvider(PaymentProvider):
    """Concrete Razorpay Payment Provider implementation interfacing with Razorpay v1 REST API."""

    def __init__(
        self,
        key_id: Optional[str] = None,
        key_secret: Optional[str] = None,
        base_url: str = "https://api.razorpay.com/v1",
    ):
        self.key_id = key_id or os.environ.get("RAZORPAY_KEY_ID", "rzp_test_mock_key")
        self.key_secret = key_secret or os.environ.get("RAZORPAY_KEY_SECRET", "mock_secret")
        self.base_url = base_url.rstrip("/")

    def _get_auth_header(self) -> str:
        """Construct Basic Auth header string."""
        credentials = f"{self.key_id}:{self.key_secret}"
        encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
        return f"Basic {encoded}"

    def trigger_retry(
        self,
        payment_id: str,
        amount: Decimal,
        currency: str = "INR",
        idempotency_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ProviderResponse:
        """Trigger payment gateway retry via Razorpay API (or fallback for mock test keys)."""
        start_t = time.time()
        amount_paise = int(amount * 100)

        # Handle test/mock API keys cleanly
        if self.key_id.startswith("rzp_test_mock") or "mock" in self.key_id:
            latency_ms = round((time.time() - start_t) * 1000 + 10.0, 2)
            tx_id = f"pay_rzp_retry_{payment_id[:8]}"
            return ProviderResponse(
                success=True,
                transaction_id=tx_id,
                status="INITIATED",
                latency_ms=latency_ms,
                raw_response={
                    "id": tx_id,
                    "entity": "payment",
                    "status": "initiated",
                    "amount": amount_paise,
                    "currency": currency,
                    "idempotency_key": idempotency_key,
                },
            )

        url = f"{self.base_url}/payments/{payment_id}/retry"
        payload = {
            "amount": amount_paise,
            "currency": currency,
            "notes": metadata or {},
        }
        if idempotency_key:
            payload["receipt"] = idempotency_key

        headers = {
            "Authorization": self._get_auth_header(),
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["X-Razorpay-Idempotency-Key"] = idempotency_key

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                latency_ms = round((time.time() - start_t) * 1000, 2)
                return ProviderResponse(
                    success=True,
                    transaction_id=data.get("id"),
                    status=data.get("status", "INITIATED"),
                    latency_ms=latency_ms,
                    raw_response=data,
                )
        except urllib.error.HTTPError as e:
            latency_ms = round((time.time() - start_t) * 1000, 2)
            err_body = e.read().decode("utf-8") if e.fp else str(e)
            return ProviderResponse(
                success=False,
                status="FAILED",
                error_message=f"Razorpay HTTP Error {e.code}: {err_body}",
                error_code=str(e.code),
                latency_ms=latency_ms,
            )
        except Exception as ex:
            latency_ms = round((time.time() - start_t) * 1000, 2)
            return ProviderResponse(
                success=False,
                status="FAILED",
                error_message=str(ex),
                error_code="NETWORK_ERROR",
                latency_ms=latency_ms,
            )

    def create_payment_link(
        self,
        amount: Decimal,
        original_amount: Decimal,
        discount_percent: Decimal,
        description: str,
        customer_details: Dict[str, Any],
        idempotency_key: Optional[str] = None,
        expires_in_hours: int = 24,
    ) -> PaymentLinkResponse:
        """Create hosted payment link via Razorpay Payment Links API."""
        start_t = time.time()
        amount_paise = int(amount * 100)
        expires_at_dt = datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)
        expire_by_timestamp = int(expires_at_dt.timestamp())

        # Handle test/mock API keys cleanly
        if self.key_id.startswith("rzp_test_mock") or "mock" in self.key_id:
            latency_ms = round((time.time() - start_t) * 1000 + 12.0, 2)
            link_id = f"plink_rzp_{idempotency_key[-10:] if idempotency_key else 'demo'}"
            short_url = f"https://rzp.io/i/{link_id[6:]}"
            return PaymentLinkResponse(
                success=True,
                link_id=link_id,
                short_url=short_url,
                amount=amount,
                original_amount=original_amount,
                discount_percent=discount_percent,
                expires_at=expires_at_dt,
                status="issued",
                latency_ms=latency_ms,
                raw_response={
                    "id": link_id,
                    "entity": "payment_link",
                    "amount": amount_paise,
                    "currency": "INR",
                    "status": "issued",
                    "short_url": short_url,
                    "reference_id": idempotency_key,
                },
            )

        url = f"{self.base_url}/payment_links"
        payload = {
            "amount": amount_paise,
            "currency": "INR",
            "accept_partial": False,
            "description": description,
            "customer": {
                "name": customer_details.get("name", "Customer"),
                "email": customer_details.get("email", ""),
                "contact": customer_details.get("phone", ""),
            },
            "notify": {"sms": True, "email": True},
            "reminder_enable": True,
            "expire_by": expire_by_timestamp,
            "notes": {
                "original_amount": str(original_amount),
                "discount_percent": str(discount_percent),
                "net_amount": str(amount),
                "idempotency_key": idempotency_key or "",
            },
        }
        if idempotency_key:
            payload["reference_id"] = idempotency_key

        headers = {
            "Authorization": self._get_auth_header(),
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["X-Razorpay-Idempotency-Key"] = idempotency_key

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                latency_ms = round((time.time() - start_t) * 1000, 2)
                canonical_short_url = data.get("short_url")
                return PaymentLinkResponse(
                    success=True,
                    link_id=data.get("id"),
                    short_url=canonical_short_url,
                    amount=amount,
                    original_amount=original_amount,
                    discount_percent=discount_percent,
                    expires_at=expires_at_dt,
                    status=data.get("status", "issued"),
                    latency_ms=latency_ms,
                    raw_response=data,
                )
        except urllib.error.HTTPError as e:
            latency_ms = round((time.time() - start_t) * 1000, 2)
            err_body = e.read().decode("utf-8") if e.fp else str(e)
            return PaymentLinkResponse(
                success=False,
                status="FAILED",
                error_message=f"Razorpay Payment Link API HTTP Error {e.code}: {err_body}",
                error_code=str(e.code),
                latency_ms=latency_ms,
            )
        except Exception as ex:
            latency_ms = round((time.time() - start_t) * 1000, 2)
            return PaymentLinkResponse(
                success=False,
                status="FAILED",
                error_message=str(ex),
                error_code="NETWORK_ERROR",
                latency_ms=latency_ms,
            )

    def get_payment_status(self, payment_id: str) -> ProviderResponse:
        """Query Razorpay API for transaction status."""
        start_t = time.time()
        if self.key_id.startswith("rzp_test_mock") or "mock" in self.key_id:
            return ProviderResponse(
                success=True,
                transaction_id=payment_id,
                status="INITIATED",
                latency_ms=5.0,
            )

        url = f"{self.base_url}/payments/{payment_id}"
        headers = {"Authorization": self._get_auth_header()}
        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                latency_ms = round((time.time() - start_t) * 1000, 2)
                return ProviderResponse(
                    success=True,
                    transaction_id=data.get("id"),
                    status=data.get("status", "UNKNOWN"),
                    latency_ms=latency_ms,
                    raw_response=data,
                )
        except Exception as ex:
            return ProviderResponse(
                success=False,
                status="FAILED",
                error_message=str(ex),
                latency_ms=round((time.time() - start_t) * 1000, 2),
            )

    def get_link_status(self, link_id: str) -> PaymentLinkResponse:
        """Query Razorpay Payment Links API for link status."""
        start_t = time.time()
        if self.key_id.startswith("rzp_test_mock") or "mock" in self.key_id:
            return PaymentLinkResponse(
                success=True,
                link_id=link_id,
                status="issued",
                latency_ms=5.0,
            )

        url = f"{self.base_url}/payment_links/{link_id}"
        headers = {"Authorization": self._get_auth_header()}
        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                latency_ms = round((time.time() - start_t) * 1000, 2)
                return PaymentLinkResponse(
                    success=True,
                    link_id=data.get("id"),
                    short_url=data.get("short_url"),
                    status=data.get("status", "UNKNOWN"),
                    latency_ms=latency_ms,
                    raw_response=data,
                )
        except Exception as ex:
            return PaymentLinkResponse(
                success=False,
                status="FAILED",
                error_message=str(ex),
                latency_ms=round((time.time() - start_t) * 1000, 2),
            )
