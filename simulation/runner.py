"""
Batch Simulation Orchestrator Module

This module drives reproducible batch simulations of e-commerce payment failure transactions.

Responsibilities:
1. Population Generation: Generates realistic combinations of customer personas and failure scenarios.
2. Webhook Pipeline Execution: Ingests failure events through process_failed_payment_event.
3. Gate & Policy Evaluation: Evaluates eligibility, risk gate, and merchant policies.
4. M9 ActionExecutor: Executes the selected recovery action through provider abstraction (Treatment & Control).
5. M10 CustomerCommunicationAgent: Dispatches customer-facing recovery communications.
6. Outcome Simulation: Simulates customer response based on persona attributes and action type.
7. A/B Differentiation: TREATMENT runs full RecoverAI pipeline; CONTROL runs baseline strategy.
8. Reproducibility: Deterministic IDs from seed + iteration index + run_tag.
9. Exception Isolation: Wraps individual transaction iterations so anomalies do not crash batches.
"""

import argparse
import random
import logging
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from backend.app.models.models import (
    Customer, Order, Payment, RecoveryCase, WebhookEvent, Outcome, AgentDecision, PaymentAttempt, NotificationEvent, GatewayRouteStatus
)
from backend.app.recovery.case_manager import process_failed_payment_event, process_captured_payment_event
from backend.app.recovery.eligibility import evaluate_eligibility
from backend.app.risk.gate import evaluate_risk
from backend.app.policies.engine import evaluate_policy
from backend.app.experiments.assigner import assign_case_to_experiment
from backend.app.analytics.degradation import normalize_route, utc_now
from simulation.personas import get_random_persona, sample_customer_ltv, PERSONA_PROFILES
from simulation.scenarios import get_random_scenario, generate_failed_webhook_payload, generate_captured_webhook_payload, FailureScenario

logger = logging.getLogger(__name__)


def _compute_recovery_probability(
    persona,
    scenario,
    group: str,
    action_type: Optional[str] = None,
) -> float:
    """Compute recovery probability based on persona attributes, scenario, and experiment group."""
    if group == "NO_INTERVENTION":
        return persona.self_retry_propensity * scenario.natural_recovery_prob

    base_prob = (persona.responsiveness * 0.5) + (scenario.natural_recovery_prob * 0.5)

    if group == "CONTROL":
        return min(0.90, base_prob)

    # TREATMENT: action-type-specific modifiers using persona attributes
    action_boost = 0.0
    if action_type:
        if action_type in ("DISCOUNTED_PAYMENT_LINK_5", "DISCOUNTED_PAYMENT_LINK_10"):
            discount_val = 0.10 if "10" in action_type else 0.05
            action_boost = 0.25 * (1.0 + persona.discount_sensitivity * discount_val * 5.0)
        elif action_type == "INSTANT_PAYMENT_LINK":
            action_boost = 0.20 * persona.responsiveness
        elif action_type == "RETRY":
            action_boost = 0.15 * persona.self_retry_propensity
        elif action_type == "WHATSAPP_INTERACTIVE":
            action_boost = 0.18 * persona.responsiveness

    return min(0.95, base_prob + action_boost)


def process_simulation_case(
    case_index: int,
    seed: int,
    db: Session,
    preset: Optional[Any] = None,
    run_tag: Optional[str] = None,
    auto_process: bool = True
) -> Dict[str, Any]:
    """Process a single simulation case (either from random sampling or a preset)."""
    random.seed(seed * 10000 + case_index)
    tag = run_tag or f"sim_{seed}"

    if preset:
        tag = run_tag or f"preset_{preset.name.lower()}_{seed}"
        persona = PERSONA_PROFILES.get(preset.persona_key, get_random_persona())
        scenario = FailureScenario(
            name=f"preset_{preset.name}",
            error_reason=preset.failure_reason,
            description=f"Preset scenario for {preset.name}",
            frequency_weight=1.0,
            natural_recovery_prob=0.5,
            default_method=preset.payment_method,
            bank=preset.bank
        )
        ext_cust_id = f"{preset.customer_id}_{tag}"
        order_id_str = f"ord_{preset.name.lower()}_{tag}"
        payment_id_str = f"pay_{preset.name.lower()}_{tag}"
        event_id_str = f"evt_{preset.name.lower()}_{tag}"
        amount_inr = preset.amount_inr
        is_opted_out = preset.is_opted_out
        forced_group = preset.experiment_group

        # Seed or reset route degradation into GatewayRouteStatus DB table
        gw_norm, pm_norm, b_norm = normalize_route(preset.gateway, preset.payment_method, preset.bank)
        route_st = db.query(GatewayRouteStatus).filter(
            GatewayRouteStatus.gateway == gw_norm,
            GatewayRouteStatus.payment_method == pm_norm,
            GatewayRouteStatus.bank == b_norm,
        ).first()
        now_dt = utc_now()
        if preset.route_degraded:
            if not route_st:
                route_st = GatewayRouteStatus(
                    gateway=gw_norm,
                    payment_method=pm_norm,
                    bank=b_norm,
                    status="CONFIRMED",
                    current_failure_rate=0.85,
                    current_z_score=3.5,
                    total_attempts=30,
                    failed_attempts=25,
                    baseline_failure_rate=0.05,
                    last_evaluated_at=now_dt,
                    last_state_change=now_dt
                )
                db.add(route_st)
            else:
                route_st.status = "CONFIRMED"
                route_st.current_failure_rate = 0.85
                route_st.current_z_score = 3.5
                route_st.total_attempts = 30
                route_st.failed_attempts = 25
                route_st.last_evaluated_at = now_dt
                route_st.last_state_change = now_dt
        else:
            if route_st and route_st.status != "NORMAL":
                route_st.status = "NORMAL"
                route_st.current_failure_rate = 0.05
                route_st.current_z_score = 0.0
                route_st.last_evaluated_at = now_dt
                route_st.last_state_change = now_dt
        db.commit()
    else:
        persona = get_random_persona()
        scenario = get_random_scenario()
        ext_cust_id = f"sim_cust_{tag}_{case_index:04d}"
        order_id_str = f"sim_ord_{tag}_{case_index:04d}"
        payment_id_str = f"sim_pay_{tag}_{case_index:04d}"
        event_id_str = f"sim_evt_{tag}_{case_index:04d}"
        amount_inr = round(random.uniform(499.0, 12999.0), 2)
        is_opted_out = random.random() < persona.opt_out_prob
        forced_group = None

    # Upsert customer
    cust = db.query(Customer).filter(Customer.external_customer_id == ext_cust_id).first()
    if not cust:
        cust = Customer(
            external_customer_id=ext_cust_id,
            customer_segment=persona.segment,
            lifetime_value=preset.lifetime_value if preset else sample_customer_ltv(persona),
            opt_out=is_opted_out,
            preferred_channel=persona.preferred_channel
        )
        db.add(cust)
    else:
        cust.opt_out = is_opted_out
    db.commit()

    # Ingest Failed Webhook Event
    failed_payload = generate_failed_webhook_payload(
        event_id=event_id_str,
        order_id=order_id_str,
        payment_id=payment_id_str,
        customer_id=ext_cust_id,
        amount_inr=amount_inr,
        scenario=scenario
    )

    case = process_failed_payment_event(db, failed_payload)

    # Assign case to A/B Experiment with forced group persistence
    assign_res = assign_case_to_experiment(db, case.id, seed=seed, forced_group=forced_group)
    group_name = assign_res.group
    selected_action_type = None

    if auto_process:
        elig_res = evaluate_eligibility(db, case.id)

        if elig_res.is_eligible:
            risk_res = evaluate_risk(db, case.id)

            if group_name == "TREATMENT":
                # M8: ENV Action Selection
                try:
                    from backend.app.recovery.env_engine import select_optimal_recovery_action
                    env_result = select_optimal_recovery_action(db, case.id)
                    selected_action_type = env_result.selected_action if env_result else None
                except Exception as env_err:
                    logger.warning(f"ENV action selection error for case #{case.id}: {env_err}")

                if risk_res.decision == "ALLOW":
                    evaluate_policy(db, case.id, action_type=selected_action_type or "PAYMENT_LINK")

                    # M9: ActionExecutor
                    agent_dec = db.query(AgentDecision).filter(
                        AgentDecision.recovery_case_id == case.id
                    ).order_by(AgentDecision.id.desc()).first()

                    action_record = None
                    if agent_dec:
                        try:
                            from backend.app.recovery.executor import ActionExecutor
                            executor = ActionExecutor()
                            action_record, provider_resp = executor.execute_decision(
                                db, case.id, agent_dec
                            )
                        except Exception as exec_err:
                            logger.warning(f"M9 ActionExecutor error for case #{case.id}: {exec_err}")

                    # M10: CustomerCommunicationAgent
                    if action_record and action_record.status == "EXECUTED":
                        channel = (persona.preferred_channel or "whatsapp").upper()
                        try:
                            from backend.app.communication.customer_agent import CustomerCommunicationAgent
                            comm_agent = CustomerCommunicationAgent(db, provider_name="mock")
                            comm_agent.process_and_dispatch(
                                recovery_case_id=case.id,
                                recovery_action_id=action_record.id,
                                channel=channel,
                            )
                        except Exception as comm_err:
                            logger.warning(f"M10 communication error for case #{case.id}: {comm_err}")

            elif group_name == "CONTROL":
                from backend.app.experiments.baselines import get_baseline_action
                from backend.app.recovery.executor import ActionExecutor
                baseline = get_baseline_action("STATIC_RETRY")
                selected_action_type = baseline.action_type

                if risk_res.decision == "ALLOW":
                    evaluate_policy(db, case.id, action_type=baseline.action_type)

                    agent_dec = AgentDecision(
                        recovery_case_id=case.id,
                        selected_action=baseline.action_type,
                        diagnosis_summary="Static 24-hour baseline retry",
                        confidence_score=1.0,
                        provider="mock",
                        model_name="Baseline_Static_Retry",
                        reasoning='{"baseline": "STATIC_RETRY"}'
                    )
                    db.add(agent_dec)
                    db.commit()

                    try:
                        executor = ActionExecutor()
                        executor.execute_decision(db, case.id, agent_dec)
                    except Exception as ctrl_err:
                        logger.warning(f"Control action execution error for case #{case.id}: {ctrl_err}")
            else:
                selected_action_type = "NO_ACTION"

            # Outcome Simulation
            if risk_res.decision == "ALLOW" or group_name == "NO_INTERVENTION":
                if preset and preset.expected_outcome:
                    is_recovered = (preset.expected_outcome == "RECOVERED")
                else:
                    recovery_prob = _compute_recovery_probability(
                        persona, scenario, group_name, selected_action_type
                    )
                    is_recovered = random.random() < recovery_prob

                outcome = db.query(Outcome).filter(Outcome.case_id == case.id).first()
                if not outcome:
                    outcome = Outcome(case_id=case.id)
                    db.add(outcome)

                if is_recovered:
                    cap_evt_id = f"sim_cap_evt_{tag}_{case_index:04d}" if not preset else f"cap_evt_{preset.name.lower()}"
                    captured_payload = generate_captured_webhook_payload(
                        event_id=cap_evt_id,
                        order_id=order_id_str,
                        payment_id=payment_id_str,
                        amount_inr=amount_inr
                    )
                    process_captured_payment_event(db, captured_payload)

                    # Handle refund processing through AttributionEngine
                    if preset and preset.refund_amount and preset.refund_amount > 0:
                        try:
                            from backend.app.analytics.attribution import AttributionEngine
                            AttributionEngine.process_refund_deduction(
                                db=db,
                                razorpay_refund_id=f"rfnd_{preset.name.lower()}",
                                payment_id=case.payment_id,
                                refund_amount=preset.refund_amount
                            )
                        except Exception as ref_err:
                            logger.warning(f"Refund deduction processing error for case #{case.id}: {ref_err}")

    # Re-query case and notification details
    db.refresh(case)

    notif_event = db.query(NotificationEvent).filter(
        NotificationEvent.recovery_case_id == case.id
    ).order_by(NotificationEvent.id.desc()).first()

    notif_status = notif_event.delivery_status if notif_event else None

    # Stored assignment group
    from backend.app.models.models import ExperimentAssignment
    exp_assign = db.query(ExperimentAssignment).filter(ExperimentAssignment.case_id == case.id).first()
    stored_group = exp_assign.group if exp_assign else group_name

    return {
        "case_id": case.id,
        "customer_external_id": ext_cust_id,
        "persona": persona.name,
        "scenario": scenario.name,
        "amount_at_risk": amount_inr,
        "experiment_group": stored_group,
        "chosen_action": selected_action_type or "NO_ACTION",
        "recovery_status": case.status,
        "notification_status": notif_status,
    }


def run_simulation_batch(
    db: Session,
    num_cases: int = 50,
    random_seed: int = 42,
    auto_process: bool = True,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Runs a batch simulation generating synthetic payment failures."""
    random.seed(random_seed)
    run_tag = run_id or f"s{random_seed}"

    created_case_ids: List[int] = []
    status_counts: Dict[str, int] = {}
    persona_counts: Dict[str, int] = {}
    scenario_counts: Dict[str, int] = {}
    group_counts: Dict[str, int] = {}
    action_counts: Dict[str, int] = {}

    total_amount_at_risk = 0.0
    total_recovered_amount = 0.0
    failed_iterations_count = 0

    for i in range(1, num_cases + 1):
        try:
            res = process_simulation_case(
                case_index=i,
                seed=random_seed,
                db=db,
                run_tag=run_tag,
                auto_process=auto_process
            )
            created_case_ids.append(res["case_id"])
            total_amount_at_risk += res["amount_at_risk"]
            if res["recovery_status"] == "RECOVERED":
                total_recovered_amount += res["amount_at_risk"]

            status_counts[res["recovery_status"]] = status_counts.get(res["recovery_status"], 0) + 1
            persona_counts[res["persona"]] = persona_counts.get(res["persona"], 0) + 1
            scenario_counts[res["scenario"]] = scenario_counts.get(res["scenario"], 0) + 1
            group_counts[res["experiment_group"]] = group_counts.get(res["experiment_group"], 0) + 1
            action_counts[res["chosen_action"]] = action_counts.get(res["chosen_action"], 0) + 1

        except Exception as e:
            failed_iterations_count += 1
            logger.error(f"Error processing simulation iteration #{i}: {e}", exc_info=True)

    recovered_count = status_counts.get("RECOVERED", 0)
    net_recovery_rate = (recovered_count / num_cases) if num_cases > 0 else 0.0

    return {
        "run_tag": run_tag,
        "random_seed": random_seed,
        "simulation_seed": random_seed,
        "total_cases_generated": len(created_case_ids),
        "successful_cases": len(created_case_ids),
        "failed_iterations": failed_iterations_count,
        "total_amount_at_risk": round(total_amount_at_risk, 2),
        "total_recovered_amount": round(total_recovered_amount, 2),
        "net_recovery_rate": round(net_recovery_rate, 4),
        "recovery_rate_pct": round(net_recovery_rate * 100.0, 2),
        "status_breakdown": status_counts,
        "persona_breakdown": persona_counts,
        "scenario_breakdown": scenario_counts,
        "experiment_group_breakdown": group_counts,
        "action_breakdown": action_counts,
        "case_ids": created_case_ids,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RecoverAI Batch Simulation Runner CLI")
    parser.add_argument("--cases", type=int, default=50, help="Number of payment failure cases to generate")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for simulation reproducibility")
    parser.add_argument("--run-id", type=str, default=None, help="Optional run tag ID")
    args = parser.parse_args()

    from backend.app.core.database import SessionLocal

    db = SessionLocal()
    try:
        summary = run_simulation_batch(
            db=db,
            num_cases=args.cases,
            random_seed=args.seed,
            run_id=args.run_id
        )
        print("==================================================")
        print("🎲 RecoverAI Simulation Completed Successfully")
        print(f"  - Run Tag: {summary['run_tag']}")
        print(f"  - Total Cases: {summary['total_cases_generated']}")
        print(f"  - Total At Risk: ₹{summary['total_amount_at_risk']:,.2f}")
        print(f"  - Total Recovered: ₹{summary['total_recovered_amount']:,.2f}")
        print(f"  - Net Recovery Rate: {summary['net_recovery_rate'] * 100:.1f}%")
        print("  - Actions Taken:", summary["action_breakdown"])
        print("==================================================")
    finally:
        db.close()
