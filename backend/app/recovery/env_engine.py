"""Expected Net Value (ENV) Calculation & Optimal Action Selection Engine.

Evaluates absolute ENV and Incremental ENV vs NO_ACTION across candidate actions.
Enforces Risk Gate & Policy Engine filtering, margin protection guardrails,
deterministic tie-breaking, and concurrency-safe PostgreSQL AgentDecision audit logging.
"""

import json
from typing import List, Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from backend.app.models.models import RecoveryCase, AgentDecision
from backend.app.ml.schemas import MLFeatureVector
from backend.app.ml.predict import predict_recovery_probability
from backend.app.ml.features import extract_features_from_case
from backend.app.recovery.candidate_actions import CandidateAction, ActionType, get_all_candidate_actions
from backend.app.recovery.action_probability import estimate_action_recovery_probability
from backend.app.policies.engine import evaluate_policy
from backend.app.risk.gate import evaluate_risk

ENV_ENGINE_VERSION = "env_v1"


class ENVBreakdown(BaseModel):
    action_type: str
    channel: str
    eligible: bool
    rejection_reason: Optional[str] = None
    p_recovery: Optional[float] = None
    expected_gross_revenue: Optional[float] = None
    gateway_cost: Optional[float] = None
    comm_cost: Optional[float] = None
    expected_discount_cost: Optional[float] = None
    fatigue_penalty: Optional[float] = None
    env: Optional[float] = None
    incremental_env: Optional[float] = None


class ENVDecisionResult(BaseModel):
    case_id: int
    base_probability: float
    prediction_source: str
    selected_action: str
    selected_env: float
    selected_incremental_env: float
    selected_p_recovery: float
    idempotent_reused: bool = False
    breakdown: List[ENVBreakdown]


def compute_action_env(
    amount: float,
    base_p: float,
    vector: MLFeatureVector,
    action: CandidateAction,
    no_action_env: float
) -> ENVBreakdown:
    """Compute mathematical absolute & incremental ENV breakdown for an ELIGIBLE action."""
    p_rec = estimate_action_recovery_probability(base_p, vector, action)
    gross_rev = round(amount * p_rec, 2)
    gw_cost = action.base_gateway_cost
    comm_cost = action.base_comm_cost
    discount_cost = round(amount * action.discount_pct * p_rec, 2)
    fatigue_penalty = round(vector.customer_failure_count_30d * action.fatigue_weight, 2)

    net_env = round(gross_rev - gw_cost - comm_cost - discount_cost - fatigue_penalty, 2)
    inc_env = round(net_env - no_action_env, 2)

    return ENVBreakdown(
        action_type=action.action_type.value,
        channel=action.channel,
        eligible=True,
        p_recovery=p_rec,
        expected_gross_revenue=gross_rev,
        gateway_cost=gw_cost,
        comm_cost=comm_cost,
        expected_discount_cost=discount_cost,
        fatigue_penalty=fatigue_penalty,
        env=net_env,
        incremental_env=inc_env
    )


def select_optimal_recovery_action(
    db: Session,
    case_id: int
) -> ENVDecisionResult:
    """Evaluate ENV across all candidate actions, enforce policies/risk gates, select a* and persist audit log.
    
    Args:
        db: SQLAlchemy database session.
        case_id: Primary key of RecoveryCase.
        
    Returns:
        ENVDecisionResult containing the optimal action and complete audit breakdown.
    """
    model_name_key = f"ENV_Engine_{ENV_ENGINE_VERSION}"

    # 0. Check Idempotency: Has a decision already been recorded for this case and model_name?
    existing = db.query(AgentDecision).filter(
        AgentDecision.recovery_case_id == case_id,
        AgentDecision.model_name == model_name_key
    ).order_by(AgentDecision.id.desc()).first()

    if existing and existing.reasoning:
        try:
            audit_data = json.loads(existing.reasoning)
            return ENVDecisionResult(
                case_id=case_id,
                base_probability=audit_data["base_probability"],
                prediction_source=audit_data.get("prediction_source", "ML"),
                selected_action=existing.selected_action,
                selected_env=audit_data["selected_env"],
                selected_incremental_env=audit_data["selected_incremental_env"],
                selected_p_recovery=existing.confidence_score if existing.confidence_score is not None else existing.confidence,
                idempotent_reused=True,
                breakdown=[ENVBreakdown(**b) for b in audit_data["breakdown"]]
            )
        except Exception:
            pass

    case = db.query(RecoveryCase).filter(RecoveryCase.id == case_id).first()
    if not case:
        raise ValueError(f"RecoveryCase {case_id} not found.")

    # 1. Feature extraction & ML prediction
    vector = extract_features_from_case(db, case_id)
    pred_out = predict_recovery_probability(db, case_id)
    base_p = pred_out.probability

    # 2. Compute Baseline NO_ACTION ENV first
    amount = float(case.amount_at_risk)
    no_action_obj = next(a for a in get_all_candidate_actions() if a.action_type == ActionType.NO_ACTION)
    no_action_bd = compute_action_env(amount, base_p, vector, no_action_obj, no_action_env=round(amount * base_p, 2))
    no_action_env = no_action_bd.env

    # 3. Risk Gate & Policy Engine Evaluation
    risk_res = evaluate_risk(db, case_id)

    candidates = get_all_candidate_actions()
    breakdowns: List[ENVBreakdown] = []

    for action in candidates:
        if action.action_type == ActionType.NO_ACTION:
            breakdowns.append(no_action_bd)
            continue

        # Check Risk Gate
        if risk_res.decision == "BLOCK":
            breakdowns.append(ENVBreakdown(
                action_type=action.action_type.value,
                channel=action.channel,
                eligible=False,
                rejection_reason=f"RiskGate Block: {risk_res.reason}"
            ))
            continue
        elif risk_res.decision == "REVIEW" and action.action_type != ActionType.MANUAL_REVIEW:
            breakdowns.append(ENVBreakdown(
                action_type=action.action_type.value,
                channel=action.channel,
                eligible=False,
                rejection_reason="RiskGate Review: Automated actions restricted"
            ))
            continue

        # Check Policy Engine constraints (proposed_discount expected as 0-100 percentage)
        policy_res = evaluate_policy(db, case_id, action.action_type.value, action.discount_pct * 100.0)
        if policy_res.decision == "BLOCK":
            breakdowns.append(ENVBreakdown(
                action_type=action.action_type.value,
                channel=action.channel,
                eligible=False,
                rejection_reason=f"Policy Reject: {policy_res.reason}"
            ))
            continue

        # Calculate ENV strictly for ELIGIBLE actions!
        bd = compute_action_env(amount, base_p, vector, action, no_action_env)
        breakdowns.append(bd)

    # 4. Filter actionable candidates (excluding NO_ACTION) with positive incremental ENV
    actionable_bds = [
        b for b in breakdowns
        if b.action_type != ActionType.NO_ACTION.value
        and b.eligible
        and b.incremental_env is not None
        and b.incremental_env > 0.0
    ]

    if actionable_bds:
        # Sort using deterministic tie-breaking:
        # 1. Higher incremental_env
        # 2. Lower total execution cost (gateway_cost + comm_cost)
        # 3. Lower priority_rank
        action_map = {a.action_type.value: a for a in candidates}
        actionable_bds.sort(key=lambda b: (
            -b.incremental_env,
            (b.gateway_cost or 0.0) + (b.comm_cost or 0.0),
            action_map[b.action_type].priority_rank
        ))
        selected = actionable_bds[0]
    else:
        # Default to NO_ACTION guardrail
        selected = no_action_bd

    selected_prob = selected.p_recovery if selected.p_recovery is not None else base_p
    selected_env_val = selected.env if selected.env is not None else no_action_env
    selected_inc_val = selected.incremental_env if selected.incremental_env is not None else 0.0

    # 5. Concurrency-Safe Audit Record Commit
    audit_data = {
        "base_probability": base_p,
        "prediction_source": pred_out.prediction_source,
        "selected_env": selected_env_val,
        "selected_incremental_env": selected_inc_val,
        "env_version": ENV_ENGINE_VERSION,
        "model_version": pred_out.model_version,
        "policy_version": "policy_v1",
        "risk_version": "risk_v1",
        "breakdown": [b.model_dump() for b in breakdowns]
    }

    agent_dec = AgentDecision(
        recovery_case_id=case_id,
        diagnosis_summary=f"ENV Engine ({ENV_ENGINE_VERSION}) evaluated {len(candidates)} candidate actions.",
        selected_action=selected.action_type,
        confidence=selected_prob,
        confidence_score=selected_prob,
        model_name=model_name_key,
        model_version=ENV_ENGINE_VERSION,
        reasoning=json.dumps(audit_data)
    )

    try:
        db.add(agent_dec)
        db.commit()
    except IntegrityError:
        db.rollback()
        # Race condition caught by unique constraint; fetch winning canonical decision
        existing = db.query(AgentDecision).filter(
            AgentDecision.recovery_case_id == case_id,
            AgentDecision.model_name == model_name_key
        ).order_by(AgentDecision.id.desc()).first()

        if existing and existing.reasoning:
            try:
                audit_data = json.loads(existing.reasoning)
                return ENVDecisionResult(
                    case_id=case_id,
                    base_probability=audit_data["base_probability"],
                    prediction_source=audit_data.get("prediction_source", "ML"),
                    selected_action=existing.selected_action,
                    selected_env=audit_data["selected_env"],
                    selected_incremental_env=audit_data["selected_incremental_env"],
                    selected_p_recovery=existing.confidence_score if existing.confidence_score is not None else existing.confidence,
                    idempotent_reused=True,
                    breakdown=[ENVBreakdown(**b) for b in audit_data["breakdown"]]
                )
            except Exception:
                pass
        
        raise RuntimeError(
            f"Decision insert conflicted for case {case_id}, but canonical AgentDecision could not be retrieved."
        )

    return ENVDecisionResult(
        case_id=case_id,
        base_probability=base_p,
        prediction_source=pred_out.prediction_source,
        selected_action=selected.action_type,
        selected_env=selected_env_val,
        selected_incremental_env=selected_inc_val,
        selected_p_recovery=selected_prob,
        idempotent_reused=False,
        breakdown=breakdowns
    )
