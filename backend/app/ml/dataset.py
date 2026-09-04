"""Dataset generator and temporal splitter for RecoverAI ML model training."""

import random
from datetime import datetime, timedelta, timezone
from typing import Tuple, List, Dict, Any
import pandas as pd
import numpy as np

from simulation.personas import PERSONA_PROFILES


def generate_historical_dataset(
    num_samples: int = 50000,
    start_time: datetime = datetime(2025, 1, 1, tzinfo=timezone.utc),
    end_time: datetime = datetime(2026, 8, 31, tzinfo=timezone.utc),
    random_seed: int = 42,
) -> pd.DataFrame:
    """Generate a realistic synthetic historical dataset with temporal timestamps.
    
    Each record represents a payment failure event at feature_timestamp and its
    eventual natural recovery outcome (target=1 if recovered naturally, target=0 otherwise).
    
    Args:
        num_samples: Number of sample cases to generate.
        start_time: Start date for simulated historical trajectory (2025-01-01).
        end_time: End date for simulated historical trajectory (2026-08-31).
        random_seed: Random seed for reproducibility.
        
    Returns:
        DataFrame containing MLFeatureVector attributes, feature_timestamp, and target label.
    """
    random.seed(random_seed)
    np.random.seed(random_seed)

    rows: List[Dict[str, Any]] = []
    persona_names = list(PERSONA_PROFILES.keys())
    payment_methods = ["UPI", "CARD", "NETBANKING"]
    failure_reasons = ["BANK_TIMEOUT", "INSUFFICIENT_FUNDS", "AUTH_FAILURE", "EXPIRED_CARD"]

    total_seconds = (end_time - start_time).total_seconds()
    avg_step = total_seconds / max(num_samples, 1)

    current_ts = start_time

    for i in range(num_samples):
        # Time progresses forward chronologically within historical window [2025-01-01, 2026-08-31]
        step = random.uniform(avg_step * 0.5, avg_step * 1.5)
        current_ts = current_ts + timedelta(seconds=step)

        persona_name = random.choice(persona_names)
        persona = PERSONA_PROFILES[persona_name]

        # Generate features from persona profile with customer-level variation
        customer_ltv = round(random.uniform(*persona.ltv_range), 2)
        amount = round(random.uniform(299.0, min(25000.0, customer_ltv * 0.8 + 1000.0)), 2)
        customer_failure_count_30d = random.choice([0, 0, 0, 1, 2, 3])
        customer_success_count_90d = random.randint(0, 20)
        attempt_number = random.choice([1, 1, 1, 2, 3])
        payment_method = random.choice(payment_methods)
        failure_reason = random.choice(failure_reasons)
        subscription = random.random() < 0.25

        # Causal ground-truth layer (hidden internal parameters)
        natural_recovery_p = persona.self_retry_propensity
        if failure_reason == "BANK_TIMEOUT":
            natural_recovery_p += 0.25
        elif failure_reason == "INSUFFICIENT_FUNDS":
            natural_recovery_p -= 0.15
        elif failure_reason == "EXPIRED_CARD":
            natural_recovery_p = 0.05

        if customer_ltv > 15000:
            natural_recovery_p += 0.10

        # Inject realistic noise to prevent artificial deterministic boundaries
        noise = random.gauss(0.0, 0.05)
        natural_recovery_p = max(0.01, min(0.99, natural_recovery_p + noise))
        target = 1 if random.random() < natural_recovery_p else 0

        # Action effects (hidden causal ground-truth for M8 / simulator)
        retry_effect = 0.05 if failure_reason == "BANK_TIMEOUT" else 0.01
        payment_link_effect = persona.responsiveness * 0.30
        discount_effect = persona.discount_sensitivity * 0.25

        rows.append({
            "case_id": i + 1000,
            "feature_timestamp": current_ts,
            "amount": amount,
            "customer_ltv": customer_ltv,
            "customer_failure_count_30d": customer_failure_count_30d,
            "customer_success_count_90d": customer_success_count_90d,
            "attempt_number": attempt_number,
            "hour": current_ts.hour,
            "day_of_week": current_ts.weekday(),
            "payment_method": payment_method,
            "failure_reason": failure_reason,
            "subscription": 1 if subscription else 0,
            # Hidden causal ground truth (for simulator / evaluation)
            "hidden_natural_recovery_p": natural_recovery_p,
            "hidden_retry_effect": retry_effect,
            "hidden_payment_link_effect": payment_link_effect,
            "hidden_discount_effect": discount_effect,
            "target": target,
        })

    df = pd.DataFrame(rows)
    return df


def temporal_split(
    df: pd.DataFrame,
    train_ratio: float = 0.70,
    val_ratio: float = 0.15,
    test_ratio: float = 0.15,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split dataset chronologically based on feature_timestamp.
    
    Guarantees max(train.feature_timestamp) < min(val.feature_timestamp)
    and max(val.feature_timestamp) < min(test.feature_timestamp).
    
    Returns:
        (train_df, val_df, test_df)
    """
    df_sorted = df.sort_values("feature_timestamp").reset_index(drop=True)
    n = len(df_sorted)

    train_end = int(n * train_ratio)
    val_end = int(n * (train_ratio + val_ratio))

    train_df = df_sorted.iloc[:train_end].copy()
    val_df = df_sorted.iloc[train_end:val_end].copy()
    test_df = df_sorted.iloc[val_end:].copy()

    return train_df, val_df, test_df
