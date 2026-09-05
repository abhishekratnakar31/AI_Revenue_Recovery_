"""
Deterministic Demo Preset Definitions for RecoverAI Simulation.

Each preset explicitly specifies persona, payment, failure scenario, experiment group,
route health, expected AI decision, expected system outcome status, and notification result.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class SimulationPreset:
    """A deterministic simulation preset for reproducible demo scenarios."""
    name: str
    display_name: str
    description: str

    # Customer
    persona_key: str
    customer_id: str
    is_opted_out: bool
    lifetime_value: float

    # Payment
    amount_inr: float
    payment_method: str
    bank: str
    failure_reason: str

    # Experiment
    experiment_group: str  # TREATMENT, CONTROL, or NO_INTERVENTION

    # Route Health
    route_degraded: bool  # If True, pre-seed CONFIRMED degradation on the route
    gateway: str

    # Expected Outcomes & System Statuses
    expected_action: str
    expected_outcome: str  # RECOVERED, NOT_RECOVERED, POLICY_BLOCKED, MANUAL_REVIEW, CUSTOMER_OPTED_OUT
    expected_notification_status: Optional[str] = None  # SENT, BLOCKED_OPT_OUT, None

    # Optional: refund after recovery
    refund_amount: Optional[float] = None

    # Additional metadata for the preset
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 7 Named Presets
# ---------------------------------------------------------------------------

PRESETS: Dict[str, SimulationPreset] = {
    "BANK_TIMEOUT_RECOVERY": SimulationPreset(
        name="BANK_TIMEOUT_RECOVERY",
        display_name="Bank Timeout Recovery",
        description="VIP customer, ₹2,500 UPI/HDFC timeout. M8 selects optimal recovery action; M9 executes; capture recovers payment.",
        persona_key="TECH_SAVVY_VIP",
        customer_id="preset_vip_timeout",
        is_opted_out=False,
        lifetime_value=45000.0,
        amount_inr=2500.00,
        payment_method="upi",
        bank="HDFC",
        failure_reason="bank_timeout",
        experiment_group="TREATMENT",
        route_degraded=False,
        gateway="razorpay",
        expected_action="DISCOUNTED_PAYMENT_LINK_10",
        expected_outcome="RECOVERED",
        expected_notification_status="SENT",
    ),

    "CONFIRMED_HDFC_DEGRADATION": SimulationPreset(
        name="CONFIRMED_HDFC_DEGRADATION",
        display_name="Confirmed HDFC Degradation",
        description="VIP customer, ₹5,000 UPI/HDFC. M11 detects route degradation and blocks retry; payment link selected.",
        persona_key="TECH_SAVVY_VIP",
        customer_id="preset_std_degradation",
        is_opted_out=False,
        lifetime_value=45000.0,
        amount_inr=5000.00,
        payment_method="upi",
        bank="HDFC",
        failure_reason="bank_timeout",
        experiment_group="TREATMENT",
        route_degraded=True,
        gateway="razorpay",
        expected_action="DISCOUNTED_PAYMENT_LINK_10",
        expected_outcome="RECOVERED",
        expected_notification_status="SENT",
    ),

    "BUDGET_DISCOUNT_RECOVERY": SimulationPreset(
        name="BUDGET_DISCOUNT_RECOVERY",
        display_name="Budget-Sensitive Discount Recovery",
        description="Budget-conscious customer, ₹1,200 insufficient funds. Discounted payment link wins ENV due to high discount sensitivity.",
        persona_key="BUDGET_CONSCIOUS",
        customer_id="preset_budget_discount",
        is_opted_out=False,
        lifetime_value=2000.0,
        amount_inr=1200.00,
        payment_method="upi",
        bank="SBI",
        failure_reason="insufficient_funds",
        experiment_group="TREATMENT",
        route_degraded=False,
        gateway="razorpay",
        expected_action="DISCOUNTED_PAYMENT_LINK_10",
        expected_outcome="RECOVERED",
        expected_notification_status="SENT",
    ),

    "HIGH_VALUE_MANUAL_REVIEW": SimulationPreset(
        name="HIGH_VALUE_MANUAL_REVIEW",
        display_name="High-Value Manual Review",
        description="VIP customer, ₹30,000 card decline. Risk gate routes to manual review due to high amount threshold.",
        persona_key="TECH_SAVVY_VIP",
        customer_id="preset_vip_highvalue",
        is_opted_out=False,
        lifetime_value=80000.0,
        amount_inr=30000.00,
        payment_method="card",
        bank="AXIS",
        failure_reason="card_expired",
        experiment_group="TREATMENT",
        route_degraded=False,
        gateway="razorpay",
        expected_action="MANUAL_REVIEW",
        expected_outcome="MANUAL_REVIEW",
        expected_notification_status=None,
    ),

    "OPTED_OUT_CUSTOMER": SimulationPreset(
        name="OPTED_OUT_CUSTOMER",
        display_name="Opted-Out Customer",
        description="High churn risk, ₹1,000 timeout, customer opted out. System blocks intervention; case status transitions to CUSTOMER_OPTED_OUT.",
        persona_key="HIGH_CHURN_RISK",
        customer_id="preset_optedout",
        is_opted_out=True,
        lifetime_value=1000.0,
        amount_inr=1000.00,
        payment_method="upi",
        bank="HDFC",
        failure_reason="bank_timeout",
        experiment_group="TREATMENT",
        route_degraded=False,
        gateway="razorpay",
        expected_action="NO_ACTION",
        expected_outcome="CUSTOMER_OPTED_OUT",
        expected_notification_status=None,
    ),

    "FRAUD_DECLINE_BLOCK": SimulationPreset(
        name="FRAUD_DECLINE_BLOCK",
        display_name="Fraud Decline Block",
        description="Standard customer, ₹8,000 fraud rejection. Risk gate blocks all automated recovery actions, setting status POLICY_BLOCKED.",
        persona_key="SUBSCRIPTION_REGULAR",
        customer_id="preset_fraud_block",
        is_opted_out=False,
        lifetime_value=15000.0,
        amount_inr=8000.00,
        payment_method="netbanking",
        bank="KOTAK",
        failure_reason="fraud_rejection",
        experiment_group="TREATMENT",
        route_degraded=False,
        gateway="razorpay",
        expected_action="NO_ACTION",
        expected_outcome="POLICY_BLOCKED",
        expected_notification_status=None,
    ),

    "REFUND_AFTER_RECOVERY": SimulationPreset(
        name="REFUND_AFTER_RECOVERY",
        display_name="Refund After Recovery",
        description="Impulsive shopper, ₹5,000 card/HDFC timeout, recovery then ₹500 partial refund. Tests net revenue attribution update.",
        persona_key="IMPULSIVE_SHOPPER",
        customer_id="preset_refund_after",
        is_opted_out=False,
        lifetime_value=8000.0,
        amount_inr=5000.00,
        payment_method="card",
        bank="HDFC",
        failure_reason="bank_timeout",
        experiment_group="TREATMENT",
        route_degraded=False,
        gateway="razorpay",
        expected_action="DISCOUNTED_PAYMENT_LINK_10",
        expected_outcome="RECOVERED",
        expected_notification_status="SENT",
        refund_amount=500.00,
    ),
}


def get_preset(name: str) -> SimulationPreset:
    """Get a preset by name. Raises KeyError if not found."""
    if name not in PRESETS:
        raise KeyError(f"Preset '{name}' not found. Available: {list(PRESETS.keys())}")
    return PRESETS[name]


def list_presets() -> list:
    """Return a list of all preset summaries."""
    return [
        {
            "name": p.name,
            "display_name": p.display_name,
            "description": p.description,
            "amount_inr": p.amount_inr,
            "persona": p.persona_key,
            "expected_action": p.expected_action,
            "expected_outcome": p.expected_outcome,
            "expected_notification_status": p.expected_notification_status,
        }
        for p in PRESETS.values()
    ]
