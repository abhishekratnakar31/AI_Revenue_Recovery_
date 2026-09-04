"""Mock Payment Provider module for RecoverAI testing and benchmark simulations.

Provides deterministic responses, tracks execution counts, and supports error injection.
"""

import time
import uuid
from decimal import Decimal
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta

from backend.app.providers.base import PaymentProvider, ProviderResponse, PaymentLinkResponse


class MockPaymentProvider(PaymentProvider):
    """Deterministic Mock Payment Provider implementation for unit tests and offline simulations."""

    def __init__(self, should_fail: bool = False, failure_reason: str = "SIMULATED_GATEWAY_TIMEOUT"):
        self.should_fail = should_fail
        self.failure_reason = failure_reason
        self.retry_call_count = 0
        self.payment_link_call_count = 0
        self.retry_history: list = []
        self.payment_link_history: list = []
        self.created_links: Dict[str, Dict[str, Any]] = {}
        self.retried_payments: Dict[str, Dict[str, Any]] = {}

    def trigger_retry(
        self,
        payment_id: str,
        amount: Decimal,
        currency: str = "INR",
        idempotency_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ProviderResponse:
        """Simulate triggering a payment gateway retry."""
        self.retry_call_count += 1
        start_t = time.time()

        record = {
            "payment_id": payment_id,
            "amount": amount,
            "currency": currency,
            "idempotency_key": idempotency_key,
            "metadata": metadata,
            "timestamp": datetime.now(timezone.utc),
        }
        self.retry_history.append(record)

        latency_ms = round((time.time() - start_t) * 1000 + 12.5, 2)

        if self.should_fail:
            return ProviderResponse(
                success=False,
                status="FAILED",
                error_message=self.failure_reason,
                error_code="MOCK_FAILURE",
                latency_ms=latency_ms,
                raw_response={"mock_status": "failed", "reason": self.failure_reason},
            )

        tx_id = f"pay_mock_retry_{uuid.uuid4().hex[:12]}"
        self.retried_payments[tx_id] = record

        return ProviderResponse(
            success=True,
            transaction_id=tx_id,
            status="INITIATED",
            latency_ms=latency_ms,
            raw_response={
                "id": tx_id,
                "entity": "payment",
                "status": "initiated",
                "amount": int(amount * 100),
                "currency": currency,
                "idempotency_key": idempotency_key,
            },
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
        """Simulate creating a hosted payment link."""
        self.payment_link_call_count += 1
        start_t = time.time()

        expires_at = datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)
        link_id = f"plink_mock_{uuid.uuid4().hex[:12]}"
        short_url = f"https://rzp.io/i/{link_id[6:]}"

        record = {
            "link_id": link_id,
            "short_url": short_url,
            "amount": amount,
            "original_amount": original_amount,
            "discount_percent": discount_percent,
            "description": description,
            "customer_details": customer_details,
            "idempotency_key": idempotency_key,
            "expires_at": expires_at,
            "status": "issued",
        }
        self.payment_link_history.append(record)
        self.created_links[link_id] = record

        latency_ms = round((time.time() - start_t) * 1000 + 15.0, 2)

        if self.should_fail:
            return PaymentLinkResponse(
                success=False,
                status="FAILED",
                error_message=self.failure_reason,
                error_code="MOCK_LINK_FAILURE",
                latency_ms=latency_ms,
                raw_response={"mock_status": "failed", "reason": self.failure_reason},
            )

        return PaymentLinkResponse(
            success=True,
            link_id=link_id,
            short_url=short_url,
            amount=amount,
            original_amount=original_amount,
            discount_percent=discount_percent,
            expires_at=expires_at,
            status="issued",
            latency_ms=latency_ms,
            raw_response={
                "id": link_id,
                "entity": "payment_link",
                "amount": int(amount * 100),
                "currency": "INR",
                "status": "issued",
                "short_url": short_url,
                "idempotency_key": idempotency_key,
            },
        )

    def get_payment_status(self, payment_id: str) -> ProviderResponse:
        """Query mock payment transaction status."""
        if payment_id in self.retried_payments:
            return ProviderResponse(
                success=True,
                transaction_id=payment_id,
                status="INITIATED",
                latency_ms=5.0,
                raw_response={"id": payment_id, "status": "initiated"},
            )
        return ProviderResponse(
            success=False,
            status="NOT_FOUND",
            error_message="Payment transaction not found in mock store",
            latency_ms=5.0,
        )

    def get_link_status(self, link_id: str) -> PaymentLinkResponse:
        """Query mock payment link status."""
        if link_id in self.created_links:
            rec = self.created_links[link_id]
            return PaymentLinkResponse(
                success=True,
                link_id=link_id,
                short_url=rec["short_url"],
                amount=rec["amount"],
                original_amount=rec["original_amount"],
                discount_percent=rec["discount_percent"],
                expires_at=rec["expires_at"],
                status=rec["status"],
                latency_ms=5.0,
                raw_response=rec,
            )
        return PaymentLinkResponse(
            success=False,
            status="NOT_FOUND",
            error_message="Payment link not found in mock store",
            latency_ms=5.0,
        )
