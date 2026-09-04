"""
Baseline Recovery Strategies Module

This module defines standard industry baseline strategies to compare against RecoverAI.

Baselines Defined:
1. STATIC_RETRY: Naive fixed retry scheduled 24 hours (1440 mins) after failure.
2. GENERIC_PAYMENT_LINK: Standard unpersonalized payment link sent 1 hour after failure without discounts.
3. NO_INTERVENTION: Zero recovery actions taken (used to measure natural recovery rates).
"""

from dataclasses import dataclass
from typing import Dict


@dataclass
class BaselineAction:
    """Dataclass holding baseline strategy parameters."""
    strategy_name: str
    action_type: str
    delay_minutes: int
    discount_percentage: float
    channel: str
    template: str


BASELINE_STRATEGIES: Dict[str, BaselineAction] = {
    "STATIC_RETRY": BaselineAction(
        strategy_name="STATIC_RETRY",
        action_type="RETRY",
        delay_minutes=1440,  # 24 hours
        discount_percentage=0.0,
        channel="system",
        template="static_system_retry"
    ),
    "GENERIC_PAYMENT_LINK": BaselineAction(
        strategy_name="GENERIC_PAYMENT_LINK",
        action_type="PAYMENT_LINK",
        delay_minutes=60,  # 1 hour
        discount_percentage=0.0,
        channel="email",
        template="generic_payment_reminder_email"
    ),
    "NO_INTERVENTION": BaselineAction(
        strategy_name="NO_INTERVENTION",
        action_type="NO_ACTION",
        delay_minutes=0,
        discount_percentage=0.0,
        channel="none",
        template="none"
    )
}


def get_baseline_action(strategy_name: str = "STATIC_RETRY") -> BaselineAction:
    """
    Returns the BaselineAction definition for a given baseline strategy name.

    Args:
        strategy_name (str): Strategy key ('STATIC_RETRY', 'GENERIC_PAYMENT_LINK', 'NO_INTERVENTION').

    Returns:
        BaselineAction: Baseline strategy configuration object.
    """
    return BASELINE_STRATEGIES.get(strategy_name, BASELINE_STRATEGIES["STATIC_RETRY"])
