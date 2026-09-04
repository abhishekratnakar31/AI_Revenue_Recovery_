"""
Merchant Diagnosis Agent for RecoverAI.
Generates structured diagnostic summaries explaining payment failure root causes, ML confidence scores,
and ENV decision logic for merchant dashboards.
"""

import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from backend.app.models.models import RecoveryCase, AgentDecision, RecoveryAction, AuditLog
from backend.app.llm import get_llm_provider, LLMProvider
from backend.app.llm.schemas import DiagnosticSummarySchema
from backend.app.communication.prompts import minimize_pii_context

logger = logging.getLogger("recoverai.communication.diagnosis_agent")


class MerchantDiagnosisAgent:
    """
    Agent responsible for explaining payment failure root causes and recovery decision reasoning to merchants.
    """

    def __init__(self, db: Session, llm_provider: Optional[LLMProvider] = None, provider_name: str = "mock"):
        self.db = db
        self.llm_provider = llm_provider or get_llm_provider(provider_name)

    def generate_report(
        self,
        recovery_case_id: int,
        agent_decision_id: Optional[int] = None,
    ) -> DiagnosticSummarySchema:
        """
        Generates a merchant-facing diagnostic report for a given recovery case.
        """
        case = self.db.query(RecoveryCase).filter(RecoveryCase.id == recovery_case_id).first()
        if not case:
            raise ValueError(f"RecoveryCase #{recovery_case_id} not found.")

        decision = None
        if agent_decision_id:
            decision = self.db.query(AgentDecision).filter(AgentDecision.id == agent_decision_id).first()
        else:
            decision = self.db.query(AgentDecision).filter(
                AgentDecision.recovery_case_id == recovery_case_id
            ).order_by(AgentDecision.id.desc()).first()

        selected_action = decision.selected_action if decision else "NO_ACTION"
        env_val = getattr(decision, "confidence", 0.0) if decision else 0.0

        case_context = {
            "case_id": case.id,
            "amount": case.amount_at_risk,
            "currency": "INR",
            "failure_reason": getattr(case, "status", "BANK_TIMEOUT"),
            "recovery_probability": case.recovery_probability or 0.0,
        }

        decision_context = {
            "selected_action": selected_action,
            "expected_net_value": env_val,
            "confidence_score": getattr(decision, "confidence_score", 0.0) if decision else 0.0,
        }

        # Invoke LLM Provider
        report = self.llm_provider.generate_merchant_diagnosis(
            case_context=case_context,
            decision_context=decision_context,
        )

        # Record AuditLog
        audit = AuditLog(
            case_id=case.id,
            actor="diagnosis_agent",
            event="MERCHANT_DIAGNOSIS_GENERATED",
            previous_state=case.status,
            new_state=case.status,
            reason=f"Generated merchant diagnosis using provider '{getattr(self.llm_provider, 'model_name', 'mock')}'.",
        )
        self.db.add(audit)
        self.db.commit()

        return report
