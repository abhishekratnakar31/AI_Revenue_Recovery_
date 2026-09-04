"""
Payment Failure Scenario Generator Module

This module generates realistic payment failure scenarios and valid Razorpay webhook JSON payloads.

Scenarios Defined:
1. BANK_TIMEOUT: Temporary bank downtime/timeout (40% frequency).
2. INSUFFICIENT_FUNDS: Account balance insufficient (30% frequency).
3. AUTH_FAILURE: OTP / 3DS authentication failure or drop-off (15% frequency).
4. EXPIRED_CARD: Card expired or invalid details (10% frequency).
5. FRAUD_BLOCK: Bank or gateway risk decline (5% frequency).
"""

import random
from dataclasses import dataclass
from typing import Dict, Any, Tuple


@dataclass
class FailureScenario:
    """Dataclass representing a payment failure scenario."""
    name: str
    error_reason: str
    description: str
    frequency_weight: float
    natural_recovery_prob: float  # Likelihood of self-retry / natural recovery
    default_method: str
    bank: str


SCENARIO_PROFILES: Dict[str, FailureScenario] = {
    "BANK_TIMEOUT": FailureScenario(
        name="Bank Timeout",
        error_reason="bank_timeout",
        description="Temporary issuer bank timeout or network downtime.",
        frequency_weight=0.40,
        natural_recovery_prob=0.65,
        default_method="card",
        bank="HDFC"
    ),
    "INSUFFICIENT_FUNDS": FailureScenario(
        name="Insufficient Funds",
        error_reason="insufficient_funds",
        description="Customer account balance insufficient for transaction.",
        frequency_weight=0.30,
        natural_recovery_prob=0.15,
        default_method="upi",
        bank="SBI"
    ),
    "AUTH_FAILURE": FailureScenario(
        name="Authentication Failure",
        error_reason="authentication_failed",
        description="Customer failed 3DS / OTP verification or closed window.",
        frequency_weight=0.15,
        natural_recovery_prob=0.40,
        default_method="upi",
        bank="ICICI"
    ),
    "EXPIRED_CARD": FailureScenario(
        name="Expired Card",
        error_reason="card_expired",
        description="Payment card expired or blocked by issuing bank.",
        frequency_weight=0.10,
        natural_recovery_prob=0.05,
        default_method="card",
        bank="AXIS"
    ),
    "FRAUD_BLOCK": FailureScenario(
        name="Fraud Block",
        error_reason="fraud_rejection",
        description="Gateway risk engine decline due to suspicious activity.",
        frequency_weight=0.05,
        natural_recovery_prob=0.00,
        default_method="netbanking",
        bank="KOTAK"
    )
}


def get_random_scenario(seed: int = None) -> FailureScenario:
    """
    Samples a FailureScenario based on realistic gateway frequency weights.
    """
    if seed is not None:
        random.seed(seed)

    keys = list(SCENARIO_PROFILES.keys())
    weights = [s.frequency_weight for s in SCENARIO_PROFILES.values()]
    chosen_key = random.choices(keys, weights=weights, k=1)[0]
    return SCENARIO_PROFILES[chosen_key]


def generate_failed_webhook_payload(
    event_id: str,
    order_id: str,
    payment_id: str,
    customer_id: str,
    amount_inr: float,
    scenario: FailureScenario = None
) -> Dict[str, Any]:
    """
    Generates a valid Razorpay `payment.failed` webhook payload dictionary.

    Args:
        event_id (str): Unique event ID.
        order_id (str): Razorpay order ID.
        payment_id (str): Razorpay payment ID.
        customer_id (str): Customer identifier.
        amount_inr (float): Amount in INR.
        scenario (FailureScenario, optional): Specific scenario to simulate.

    Returns:
        dict: Razorpay webhook payload dictionary.
    """
    scen = scenario or get_random_scenario()
    amount_paisa = int(amount_inr * 100)

    return {
        "event": "payment.failed",
        "event_id": event_id,
        "created_at": 1700000000,
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": order_id,
                    "customer_id": customer_id,
                    "amount": amount_paisa,
                    "currency": "INR",
                    "status": "failed",
                    "method": scen.default_method,
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_reason": scen.error_reason,
                    "error_description": scen.description,
                    "bank": scen.bank,
                    "acquirer_data": {
                        "bank_transaction_id": f"tx_{event_id[:8]}"
                    }
                }
            }
        }
    }


def generate_captured_webhook_payload(
    event_id: str,
    order_id: str,
    payment_id: str,
    amount_inr: float
) -> Dict[str, Any]:
    """
    Generates a valid Razorpay `payment.captured` webhook payload dictionary.
    """
    amount_paisa = int(amount_inr * 100)
    return {
        "event": "payment.captured",
        "event_id": event_id,
        "created_at": 1700000000,
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": order_id,
                    "amount": amount_paisa,
                    "currency": "INR",
                    "status": "captured"
                }
            }
        }
    }
