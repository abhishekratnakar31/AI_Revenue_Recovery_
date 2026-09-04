"""Providers package initialization for RecoverAI."""

from backend.app.providers.base import PaymentProvider, ProviderResponse, PaymentLinkResponse
from backend.app.providers.mock_provider import MockPaymentProvider
from backend.app.providers.razorpay_provider import RazorpayPaymentProvider


def get_payment_provider(provider_name: str = "mock", **kwargs) -> PaymentProvider:
    """Factory function to retrieve payment provider instance.
    
    Args:
        provider_name: "mock" or "razorpay".
        **kwargs: Provider initialization arguments.
        
    Returns:
        PaymentProvider instance.
    """
    provider_type = provider_name.lower()
    if provider_type == "razorpay":
        return RazorpayPaymentProvider(**kwargs)
    return MockPaymentProvider(**kwargs)


__all__ = [
    "PaymentProvider",
    "ProviderResponse",
    "PaymentLinkResponse",
    "MockPaymentProvider",
    "RazorpayPaymentProvider",
    "get_payment_provider",
]
