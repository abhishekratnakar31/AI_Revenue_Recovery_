"""Abstract Base Provider module for RecoverAI payment provider integrations.

Defines business-neutral dataclasses and PaymentProvider abstract base class.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Any, Optional
from datetime import datetime


@dataclass
class ProviderResponse:
    """Standardized response object for gateway operational actions (retries, refunds)."""
    success: bool
    transaction_id: Optional[str] = None
    status: str = "PENDING"
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    latency_ms: float = 0.0
    raw_response: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PaymentLinkResponse:
    """Standardized response object for payment link creation operations."""
    success: bool
    link_id: Optional[str] = None
    short_url: Optional[str] = None
    amount: Optional[Decimal] = None
    original_amount: Optional[Decimal] = None
    discount_percent: Optional[Decimal] = None
    expires_at: Optional[datetime] = None
    status: str = "CREATED"
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    latency_ms: float = 0.0
    raw_response: Dict[str, Any] = field(default_factory=dict)


class PaymentProvider(ABC):
    """Abstract Base Class for all payment gateway integrations (Razorpay, Mock, Stripe)."""

    @abstractmethod
    def trigger_retry(
        self,
        payment_id: str,
        amount: Decimal,
        currency: str = "INR",
        idempotency_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ProviderResponse:
        """Trigger an automated gateway retry for a failed transaction.
        
        Args:
            payment_id: Original gateway payment ID.
            amount: Transaction amount as Decimal.
            currency: Currency ISO code (default "INR").
            idempotency_key: Unique operation idempotency key.
            metadata: Additional merchant metadata context.
            
        Returns:
            ProviderResponse containing execution outcome and provider transaction ID.
        """
        pass

    @abstractmethod
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
        """Create a hosted payment link with optional merchant discount.
        
        Args:
            amount: Net payable amount after discount as Decimal.
            original_amount: Pre-discount original amount as Decimal.
            discount_percent: Applied discount percentage as Decimal.
            description: Payment link description string.
            customer_details: Customer profile metadata (name, email, phone).
            idempotency_key: Unique operation idempotency key.
            expires_in_hours: Expiration buffer in hours.
            
        Returns:
            PaymentLinkResponse containing canonical short_url and provider link ID.
        """
        pass

    @abstractmethod
    def get_payment_status(self, payment_id: str) -> ProviderResponse:
        """Query the payment gateway for current transaction status.
        
        Args:
            payment_id: Gateway payment transaction ID.
            
        Returns:
            ProviderResponse with current status ("captured", "failed", "pending").
        """
        pass

    @abstractmethod
    def get_link_status(self, link_id: str) -> PaymentLinkResponse:
        """Query the payment gateway for current payment link status.
        
        Args:
            link_id: Gateway payment link ID.
            
        Returns:
            PaymentLinkResponse with link status ("paid", "issued", "expired").
        """
        pass
