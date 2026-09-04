"""
Customer Persona Generator Module

This module defines customer behavioral personas for simulation, ML training, and strategy benchmarking.

Personas Defined:
1. TECH_SAVVY_VIP: High LTV, WhatsApp preference, high responsiveness, fast self-retry.
2. IMPULSIVE_SHOPPER: Medium LTV, WhatsApp/SMS preference, high response to instant payment links.
3. BUDGET_CONSCIOUS: Low/Medium LTV, Email preference, high sensitivity to discount incentives.
4. SUBSCRIPTION_REGULAR: Stable LTV, Email preference, high renewal auto-retry success.
5. HIGH_CHURN_RISK: Low LTV, SMS preference, low responsiveness, higher opt-out probability.
"""

import random
from dataclasses import dataclass
from typing import Tuple, Dict


@dataclass
class CustomerPersona:
    """Dataclass holding behavioral parameters for a customer persona."""
    name: str
    segment: str
    ltv_range: Tuple[float, float]
    preferred_channel: str
    responsiveness: float  # Probability of responding to communications [0.0 - 1.0]
    self_retry_propensity: float  # Probability of self-retrying without intervention [0.0 - 1.0]
    discount_sensitivity: float  # Sensitivity to discount incentives [0.0 - 1.0]
    opt_out_prob: float  # Probability of opting out of marketing communications [0.0 - 1.0]


# Predefined Persona Profiles
PERSONA_PROFILES: Dict[str, CustomerPersona] = {
    "TECH_SAVVY_VIP": CustomerPersona(
        name="Tech-Savvy VIP",
        segment="vip",
        ltv_range=(15000.0, 100000.0),
        preferred_channel="whatsapp",
        responsiveness=0.85,
        self_retry_propensity=0.70,
        discount_sensitivity=0.10,
        opt_out_prob=0.01
    ),
    "IMPULSIVE_SHOPPER": CustomerPersona(
        name="Impulsive Shopper",
        segment="high_value",
        ltv_range=(3000.0, 15000.0),
        preferred_channel="whatsapp",
        responsiveness=0.65,
        self_retry_propensity=0.40,
        discount_sensitivity=0.50,
        opt_out_prob=0.02
    ),
    "BUDGET_CONSCIOUS": CustomerPersona(
        name="Budget Conscious",
        segment="standard",
        ltv_range=(1000.0, 5000.0),
        preferred_channel="email",
        responsiveness=0.45,
        self_retry_propensity=0.20,
        discount_sensitivity=0.80,
        opt_out_prob=0.05
    ),
    "SUBSCRIPTION_REGULAR": CustomerPersona(
        name="Subscription Regular",
        segment="recurring",
        ltv_range=(5000.0, 30000.0),
        preferred_channel="email",
        responsiveness=0.55,
        self_retry_propensity=0.60,
        discount_sensitivity=0.20,
        opt_out_prob=0.02
    ),
    "HIGH_CHURN_RISK": CustomerPersona(
        name="High Churn Risk",
        segment="at_risk",
        ltv_range=(500.0, 2000.0),
        preferred_channel="sms",
        responsiveness=0.15,
        self_retry_propensity=0.10,
        discount_sensitivity=0.30,
        opt_out_prob=0.15
    )
}


def get_random_persona(seed: int = None) -> CustomerPersona:
    """
    Generates a randomly sampled CustomerPersona based on realistic demographic weights.

    Args:
        seed (int, optional): Random seed for reproducible generation.

    Returns:
        CustomerPersona: Sampled persona profile object.
    """
    if seed is not None:
        random.seed(seed)

    keys = list(PERSONA_PROFILES.keys())
    # Population weights: Budget (35%), Impulsive (25%), VIP (15%), Regular (15%), High Risk (10%)
    weights = [0.15, 0.25, 0.35, 0.15, 0.10]
    chosen_key = random.choices(keys, weights=weights, k=1)[0]
    return PERSONA_PROFILES[chosen_key]


def sample_customer_ltv(persona: CustomerPersona, seed: int = None) -> float:
    """
    Samples a realistic Lifetime Value (LTV) within the persona's range.
    """
    if seed is not None:
        random.seed(seed)
    min_ltv, max_ltv = persona.ltv_range
    return round(random.uniform(min_ltv, max_ltv), 2)
