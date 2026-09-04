"""
Customer Communication Agent for RecoverAI.
Orchestrates pre-LLM opt-out verification, DB-level notification idempotency,
multi-LLM copy generation, deterministic safety gate validation, and message dispatch.
"""

import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from backend.app.models.models import Customer, RecoveryCase, RecoveryAction, NotificationEvent, AuditLog
from backend.app.llm import get_llm_provider, LLMProvider
from backend.app.llm.schemas import CommunicationCopySchema
from backend.app.communication.safety import CommunicationSafetyGate
from backend.app.communication.prompts import minimize_pii_context

logger = logging.getLogger("recoverai.communication.customer_agent")


class CustomerCommunicationAgent:
    """
    Agent responsible for generating and dispatching customer-facing recovery communications safely.
    """

    def __init__(self, db: Session, llm_provider: Optional[LLMProvider] = None, provider_name: str = "mock"):
        self.db = db
        self.llm_provider = llm_provider or get_llm_provider(provider_name)

    def process_and_dispatch(
        self,
        recovery_case_id: int,
        recovery_action_id: int,
        channel: str = "WHATSAPP",
    ) -> NotificationEvent:
        """
        Processes and dispatches recovery communication for a given case and executed action.
        Guarantees:
        1. Pre-LLM opt-out check stops processing before external LLM API calls.
        2. Database-level UNIQUE(idempotency_key) prevents duplicate message dispatch.
        3. Deterministic post-LLM safety gate validates money, URLs, and SMS character limits.
        """
        ch_upper = channel.upper()

        # 1. Fetch RecoveryCase, Customer, and RecoveryAction
        case = self.db.query(RecoveryCase).filter(RecoveryCase.id == recovery_case_id).first()
        if not case:
            raise ValueError(f"RecoveryCase #{recovery_case_id} not found.")

        customer = self.db.query(Customer).filter(Customer.id == case.customer_id).first()
        if not customer:
            raise ValueError(f"Customer #{case.customer_id} not found.")

        action = self.db.query(RecoveryAction).filter(RecoveryAction.id == recovery_action_id).first()
        if not action:
            raise ValueError(f"RecoveryAction #{recovery_action_id} not found.")

        # 2. Pre-LLM Opt-Out Guardrail Check
        if getattr(customer, "opt_out", False):
            logger.info(f"Customer #{customer.id} has opted out. Halting communication pre-LLM.")

            # Record blocked notification event
            idempotency_key = f"communication_case_{recovery_case_id}_action_{recovery_action_id}_{ch_upper}"
            existing = self.db.query(NotificationEvent).filter(
                NotificationEvent.idempotency_key == idempotency_key
            ).first()

            if existing:
                return existing

            blocked_event = NotificationEvent(
                customer_id=customer.id,
                recovery_case_id=case.id,
                recovery_action_id=action.id,
                channel=ch_upper,
                notification_type="RECOVERY_COMMUNICATION",
                idempotency_key=idempotency_key,
                headline="COMMUNICATION_BLOCKED",
                message_body="Communication blocked due to customer opt-out preference.",
                cta_text="",
                delivery_status="BLOCKED_OPT_OUT",
                status_metadata={"opt_out": True, "llm_calls_made": 0},
            )
            self.db.add(blocked_event)

            # Record AuditLog
            audit = AuditLog(
                case_id=case.id,
                actor="communication_agent",
                event="COMMUNICATION_BLOCKED_OPT_OUT",
                previous_state=case.status,
                new_state=case.status,
                reason=f"Customer #{customer.id} opted out of communications.",
            )
            self.db.add(audit)
            self.db.commit()
            self.db.refresh(blocked_event)
            return blocked_event

        # 3. Deterministic Idempotency Key Generation & DB Reservation
        idempotency_key = f"communication_case_{recovery_case_id}_action_{recovery_action_id}_{ch_upper}"

        # Check existing notification event
        existing_event = self.db.query(NotificationEvent).filter(
            NotificationEvent.idempotency_key == idempotency_key
        ).first()

        if existing_event:
            logger.info(f"Idempotency hit for notification key '{idempotency_key}'. Returning existing record.")
            return existing_event

        # Attempt to insert initial CREATED record
        new_event = NotificationEvent(
            customer_id=customer.id,
            recovery_case_id=case.id,
            recovery_action_id=action.id,
            channel=ch_upper,
            notification_type="RECOVERY_COMMUNICATION",
            idempotency_key=idempotency_key,
            delivery_status="GENERATING",
        )
        try:
            self.db.add(new_event)
            self.db.commit()
            self.db.refresh(new_event)
        except IntegrityError:
            self.db.rollback()
            logger.warning(f"Concurrent insert for key '{idempotency_key}'. Fetching existing row.")
            return self.db.query(NotificationEvent).filter(
                NotificationEvent.idempotency_key == idempotency_key
            ).first()

        # 4. PII Minimization & Context Preparation
        min_context = minimize_pii_context(
            raw_customer={"first_name": customer.first_name},
            raw_case={
                "id": case.id,
                "amount_at_risk": case.amount_at_risk,
                "failure_reason": getattr(case, "status", "PAYMENT_FAILED"),
            },
            raw_action={
                "action_type": action.action_type,
                "action_metadata": action.action_metadata or {},
            },
        )

        # 5. Invoke LLM Provider
        raw_copy = self.llm_provider.generate_customer_communication(
            case_context=min_context["case"] | min_context["customer"],
            action_context=min_context["action"],
            channel=ch_upper,
        )

        # 6. Post-LLM Safety Gate Validation & Injections
        action_meta = action.action_metadata or {}
        sanitized_copy = CommunicationSafetyGate.validate_and_sanitize(
            copy=raw_copy,
            backend_context={
                "first_name": customer.first_name,
                "amount": case.amount_at_risk,
                "currency": "INR",
                "order_id": case.order_id,
            },
            action_metadata=action_meta,
            channel=ch_upper,
        )

        # Handle HTML email wrapper if channel is EMAIL
        final_body = sanitized_copy.body
        if ch_upper == "EMAIL":
            canonical_url = action_meta.get("short_url") or action_meta.get("payment_url") or ""
            final_body = CommunicationSafetyGate.render_email_template(sanitized_copy, canonical_url)

        # 7. Update NotificationEvent Record
        new_event.headline = sanitized_copy.headline
        new_event.message_body = final_body
        new_event.cta_text = sanitized_copy.cta_text
        new_event.delivery_status = "SENT"
        new_event.status_metadata = sanitized_copy.raw_response

        # 8. Record System AuditLog
        audit = AuditLog(
            case_id=case.id,
            actor="communication_agent",
            event="NOTIFICATION_DISPATCHED",
            previous_state="GENERATING",
            new_state="SENT",
            reason=f"Dispatched {ch_upper} notification to customer #{customer.id} using provider '{getattr(self.llm_provider, 'model_name', 'mock')}'.",
        )
        self.db.add(audit)
        self.db.commit()
        self.db.refresh(new_event)

        return new_event
