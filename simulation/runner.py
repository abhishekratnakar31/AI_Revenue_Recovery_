"""
Batch Simulation Orchestrator Module

This module drives reproducible batch simulations of e-commerce payment failure transactions.

Responsibilities:
1. Population Generation: Generates realistic combinations of customer personas and failure scenarios.
2. Webhook Pipeline Execution: Ingests failure events through process_failed_payment_event.
3. Gate & Policy Evaluation: Evaluates eligibility, risk gate, and merchant policies.
4. Outcome Simulation: Simulates customer response and self-retry behavior to yield true ground-truth recovery outcomes.
5. Reproducibility: Accepts a random_seed parameter ensuring 100% deterministic dataset generation.
6. Exception Isolation: Wraps individual transaction iterations so anomalies do not crash simulation batches.
"""

import random
import logging
from typing import Dict, Any, List
from sqlalchemy.orm import Session

from backend.app.models.models import Customer, Order, Payment, RecoveryCase, WebhookEvent, Outcome
from backend.app.recovery.case_manager import process_failed_payment_event, process_captured_payment_event
from backend.app.recovery.eligibility import evaluate_eligibility
from backend.app.risk.gate import evaluate_risk
from backend.app.policies.engine import evaluate_policy
from simulation.personas import get_random_persona, sample_customer_ltv
from simulation.scenarios import get_random_scenario, generate_failed_webhook_payload, generate_captured_webhook_payload

logger = logging.getLogger(__name__)


def run_simulation_batch(
    db: Session,
    num_cases: int = 50,
    random_seed: int = 42,
    auto_process: bool = True
) -> Dict[str, Any]:
    """
    Runs a batch simulation generating synthetic payment failures and processing them through RecoverAI.
    """
    random.seed(random_seed)

    created_case_ids: List[int] = []
    status_counts: Dict[str, int] = {}
    persona_counts: Dict[str, int] = {}
    scenario_counts: Dict[str, int] = {}

    total_amount_at_risk = 0.0
    total_recovered_amount = 0.0
    failed_iterations_count = 0

    for i in range(1, num_cases + 1):
        try:
            # 1. Sample Persona & Scenario
            persona = get_random_persona()
            scenario = get_random_scenario()

            persona_counts[persona.name] = persona_counts.get(persona.name, 0) + 1
            scenario_counts[scenario.name] = scenario_counts.get(scenario.name, 0) + 1

            # 2. Generate Transaction Identifiers & Amounts
            ext_cust_id = f"sim_cust_{random_seed}_{i:04d}"
            order_id_str = f"sim_ord_{random_seed}_{i:04d}"
            payment_id_str = f"sim_pay_{random_seed}_{i:04d}"
            event_id_str = f"sim_evt_{random_seed}_{i:04d}"

            amount_inr = round(random.uniform(499.0, 12999.0), 2)
            total_amount_at_risk += amount_inr

            # 3. Apply Opt-Out probability based on persona
            is_opted_out = random.random() < persona.opt_out_prob

            existing_cust = db.query(Customer).filter(Customer.external_customer_id == ext_cust_id).first()
            if not existing_cust:
                cust = Customer(
                    external_customer_id=ext_cust_id,
                    customer_segment=persona.segment,
                    lifetime_value=sample_customer_ltv(persona),
                    opt_out=is_opted_out,
                    preferred_channel=persona.preferred_channel
                )
                db.add(cust)
                db.commit()

            # 4. Generate & Ingest Failed Webhook Event
            failed_payload = generate_failed_webhook_payload(
                event_id=event_id_str,
                order_id=order_id_str,
                payment_id=payment_id_str,
                customer_id=ext_cust_id,
                amount_inr=amount_inr,
                scenario=scenario
            )

            case = process_failed_payment_event(db, failed_payload)
            created_case_ids.append(case.id)

            if not auto_process:
                continue

            # 5. Pipeline Evaluation: Eligibility -> Risk Gate -> Policy Engine
            elig_res = evaluate_eligibility(db, case.id)

            if elig_res.is_eligible:
                risk_res = evaluate_risk(db, case.id)
                if risk_res.decision == "ALLOW":
                    pol_res = evaluate_policy(db, case.id, action_type="PAYMENT_LINK")

                    # 6. Outcome Simulation: Calculate Recovery Probability
                    recovery_prob = (persona.responsiveness * 0.5) + (scenario.natural_recovery_prob * 0.5)
                    is_recovered = random.random() < recovery_prob

                    if is_recovered:
                        cap_evt_id = f"sim_cap_evt_{random_seed}_{i:04d}"
                        captured_payload = generate_captured_webhook_payload(
                            event_id=cap_evt_id,
                            order_id=order_id_str,
                            payment_id=payment_id_str,
                            amount_inr=amount_inr
                        )
                        resolved_case = process_captured_payment_event(db, captured_payload)
                        if resolved_case:
                            total_recovered_amount += amount_inr

            # Refresh case status for summary aggregation
            db.refresh(case)
            status_counts[case.status] = status_counts.get(case.status, 0) + 1

        except Exception as e:
            logger.exception(f"Error executing simulation iteration #{i}: {str(e)}")
            failed_iterations_count += 1
            db.rollback()

    recovery_rate = (total_recovered_amount / total_amount_at_risk * 100.0) if total_amount_at_risk > 0 else 0.0

    return {
        "simulation_seed": random_seed,
        "total_cases_generated": len(created_case_ids),
        "failed_iterations_count": failed_iterations_count,
        "total_amount_at_risk": round(total_amount_at_risk, 2),
        "total_recovered_amount": round(total_recovered_amount, 2),
        "recovery_rate_pct": round(recovery_rate, 2),
        "status_breakdown": status_counts,
        "persona_breakdown": persona_counts,
        "scenario_breakdown": scenario_counts
    }
