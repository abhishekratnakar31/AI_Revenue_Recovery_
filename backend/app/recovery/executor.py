"""Action Executor Engine for RecoverAI Milestone 9.

Executes deterministic recovery decisions (AgentDecision / CandidateAction) through provider abstractions.
Guarantees side-effect idempotency via pre-execution DB reservations with UNIQUE(idempotency_key) protection,
exact Decimal financial calculations, state machine progression, and audit trail logging.
"""

import time
import logging
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from typing import Tuple, Dict, Any, Optional

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from backend.app.models.models import (
    RecoveryCase,
    AgentDecision,
    RecoveryAction,
    PaymentAttempt,
    NotificationEvent,
    AuditLog,
    Customer,
    Payment,
)
from backend.app.recovery.candidate_actions import CandidateAction, ActionType, get_all_candidate_actions
from backend.app.providers.base import PaymentProvider, ProviderResponse, PaymentLinkResponse
from backend.app.providers import get_payment_provider
from backend.app.state_machine.payment_state import PaymentStateMachine

logger = logging.getLogger(__name__)


class ActionExecutor:
    """Idempotent Action Execution Engine for RecoverAI."""

    def __init__(self, provider: Optional[PaymentProvider] = None):
        """Initialize ActionExecutor with a payment provider abstraction instance.
        
        Args:
            provider: PaymentProvider instance (defaults to MockPaymentProvider if None).
        """
        self.provider = provider or get_payment_provider("mock")

    def execute_decision(
        self,
        db: Session,
        recovery_case_id: int,
        agent_decision: AgentDecision,
        provider_override: Optional[PaymentProvider] = None,
    ) -> Tuple[RecoveryAction, Any]:
        """Execute a recovery decision idempotently.
        
        Guarantees that duplicate worker calls for the same decision result in exactly
        one database reservation and exactly one external provider API invocation.
        
        Args:
            db: SQLAlchemy database session.
            recovery_case_id: Primary key of RecoveryCase.
            agent_decision: AgentDecision record selected by M8 ENV engine.
            provider_override: Optional PaymentProvider instance for this execution.
            
        Returns:
            Tuple of (RecoveryAction, ProviderResponse or PaymentLinkResponse or Dict).
        """
        provider = provider_override or self.provider
        case = db.query(RecoveryCase).filter(RecoveryCase.id == recovery_case_id).first()
        if not case:
            raise ValueError(f"RecoveryCase id={recovery_case_id} not found")

        action_type = agent_decision.selected_action

        # Validate that action_type is a recognized CandidateAction
        valid_action_types = [a.value for a in ActionType]
        if action_type not in valid_action_types:
            raise ValueError(f"Invalid selected_action '{action_type}'. Must be one of {valid_action_types}")

        # Derive immutable, deterministic idempotency key tied directly to agent_decision.id
        idempotency_key = f"action_case_{recovery_case_id}_dec_{agent_decision.id}_{action_type}"

        # -------------------------------------------------------------------------
        # STEP 1: Check DB for existing reservation / completed action
        # -------------------------------------------------------------------------
        existing_action = (
            db.query(RecoveryAction)
            .filter(RecoveryAction.idempotency_key == idempotency_key)
            .first()
        )

        if existing_action:
            if existing_action.status in ("EXECUTED", "FAILED", "TERMINAL"):
                logger.info(
                    f"[ActionExecutor] Idempotency hit: Action key '{idempotency_key}' "
                    f"already executed with status '{existing_action.status}'."
                )
                return existing_action, existing_action.action_metadata or {}

            elif existing_action.status == "EXECUTING":
                # Stale execution check (> 30 seconds threshold)
                stale_cutoff = datetime.now(timezone.utc) - timedelta(seconds=30)
                created_at = existing_action.created_at
                if created_at and created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)

                if created_at < stale_cutoff:
                    logger.warning(
                        f"[ActionExecutor] Stale EXECUTING action key '{idempotency_key}' detected. "
                        "Attempting provider reconciliation..."
                    )
                    reconciled_action, recon_resp = self._reconcile_stale_execution(
                        db, existing_action, case, provider
                    )
                    return reconciled_action, recon_resp
                else:
                    logger.info(
                        f"[ActionExecutor] Concurrent execution in progress for key '{idempotency_key}'."
                    )
                    return existing_action, {"status": "EXECUTING_IN_PROGRESS"}

        # -------------------------------------------------------------------------
        # STEP 2: Pre-execution DB reservation (status="EXECUTING")
        # -------------------------------------------------------------------------
        # Retrieve expected cost and net value from candidate action definitions
        all_actions = get_all_candidate_actions()
        cand_action = next((a for a in all_actions if a.action_type.value == action_type), all_actions[0])
        expected_cost = cand_action.base_gateway_cost + cand_action.base_comm_cost
        expected_recovery = float(case.amount_at_risk) * 0.5
        expected_net_value = expected_recovery - expected_cost

        action_record = RecoveryAction(
            recovery_case_id=recovery_case_id,
            action_type=action_type,
            idempotency_key=idempotency_key,
            expected_recovery=expected_recovery,
            expected_cost=expected_cost,
            expected_net_value=expected_net_value,
            status="EXECUTING",
            provider="razorpay" if provider.__class__.__name__ == "RazorpayPaymentProvider" else "mock",
            action_metadata={
                "agent_decision_id": agent_decision.id,
                "idempotency_key": idempotency_key,
                "execution_started_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        try:
            db.add(action_record)
            db.commit()
            db.refresh(action_record)
        except IntegrityError:
            db.rollback()
            logger.info(
                f"[ActionExecutor] Concurrent worker collision caught via UNIQUE({idempotency_key}). "
                "Retrieving canonical pre-reserved record."
            )
            canonical = (
                db.query(RecoveryAction)
                .filter(RecoveryAction.idempotency_key == idempotency_key)
                .first()
            )
            return canonical, canonical.action_metadata or {}

        # -------------------------------------------------------------------------
        # STEP 3: Dispatch to Action Handlers
        # -------------------------------------------------------------------------
        try:
            if action_type == ActionType.NO_ACTION.value:
                return self._execute_no_action(db, action_record, case, agent_decision)

            elif action_type == ActionType.RETRY.value:
                return self._execute_retry(db, action_record, case, agent_decision, provider)

            elif action_type in (
                ActionType.INSTANT_PAYMENT_LINK.value,
                ActionType.DISCOUNTED_PAYMENT_LINK_5.value,
                ActionType.DISCOUNTED_PAYMENT_LINK_10.value,
            ):
                return self._execute_payment_link(db, action_record, case, agent_decision, provider)

            elif action_type == ActionType.MANUAL_REVIEW.value:
                return self._execute_manual_review(db, action_record, case, agent_decision)

            else:
                raise ValueError(f"Unhandled action type: {action_type}")

        except Exception as ex:
            logger.error(f"[ActionExecutor] Unexpected failure executing action '{action_type}': {ex}")
            action_record.status = "FAILED"
            action_record.outcome = "EXECUTION_EXCEPTION"
            action_record.action_metadata = {
                **(action_record.action_metadata or {}),
                "error_message": str(ex),
                "failed_at": datetime.now(timezone.utc).isoformat(),
            }
            db.commit()
            raise ex

    # -------------------------------------------------------------------------
    # Action Handlers
    # -------------------------------------------------------------------------

    def _execute_no_action(
        self,
        db: Session,
        action: RecoveryAction,
        case: RecoveryCase,
        agent_decision: AgentDecision,
    ) -> Tuple[RecoveryAction, Dict[str, Any]]:
        """Handle NO_ACTION execution."""
        start_state = case.status
        action.status = "EXECUTED"
        action.executed_at = datetime.now(timezone.utc)
        action.outcome = "NO_ACTION_TAKEN"

        action.action_metadata = {
            **(action.action_metadata or {}),
            "original_amount": str(Decimal(str(case.amount_at_risk))),
            "discount_pct": "0.0",
            "net_amount": str(Decimal(str(case.amount_at_risk))),
            "execution_completed_at": datetime.now(timezone.utc).isoformat(),
        }

        # Transition state machine
        if PaymentStateMachine.can_transition(case.status, "RECOVERY_ACTIVE"):
            case.status = PaymentStateMachine.transition(case.status, "RECOVERY_ACTIVE")

        # System Audit Log
        self._log_audit(
            db=db,
            case_id=case.id,
            event="ACTION_EXECUTED_NO_ACTION",
            previous_state=start_state,
            new_state=case.status,
            reason=f"Executed NO_ACTION decision {agent_decision.id}",
            metadata=action.action_metadata,
        )

        db.commit()
        db.refresh(action)
        return action, {"status": "EXECUTED", "outcome": "NO_ACTION_TAKEN"}

    def _execute_retry(
        self,
        db: Session,
        action: RecoveryAction,
        case: RecoveryCase,
        agent_decision: AgentDecision,
        provider: PaymentProvider,
    ) -> Tuple[RecoveryAction, ProviderResponse]:
        """Handle RETRY execution."""
        start_state = case.status

        # Financial Decimal calculations
        amount_dec = Decimal(str(case.amount_at_risk))

        # Retrieve payment ID for gateway retry
        payment_id_str = f"pay_case_{case.id}"
        if case.payment:
            payment_id_str = case.payment.razorpay_payment_id

        # Invoke provider
        resp = provider.trigger_retry(
            payment_id=payment_id_str,
            amount=amount_dec,
            currency="INR",
            idempotency_key=action.idempotency_key,
            metadata={"case_id": case.id, "decision_id": agent_decision.id},
        )

        # Update last_probe_at on GatewayRouteStatus if route status exists
        from backend.app.models.models import GatewayRouteStatus, PaymentAttempt
        from backend.app.analytics.degradation import normalize_route
        attempt = db.query(PaymentAttempt).filter(PaymentAttempt.payment_id == case.payment_id).order_by(PaymentAttempt.timestamp.desc()).first() if case.payment_id else None
        payment = case.payment
        gw = getattr(attempt, "gateway", None) or getattr(payment, "gateway", "razorpay")
        pm = getattr(attempt, "payment_method", None) or getattr(payment, "payment_method", "CARD")
        b = getattr(attempt, "bank", None) or "UNKNOWN"
        gw_n, pm_n, b_n = normalize_route(gw, pm, b)
        route_st = db.query(GatewayRouteStatus).filter(
            GatewayRouteStatus.gateway == gw_n,
            GatewayRouteStatus.payment_method == pm_n,
            GatewayRouteStatus.bank == b_n,
        ).first()
        if route_st:
            route_st.last_probe_at = datetime.now(timezone.utc)

        action.executed_at = datetime.now(timezone.utc)
        action.provider_transaction_id = resp.transaction_id

        meta = {
            **(action.action_metadata or {}),
            "original_amount": str(amount_dec),
            "discount_pct": "0.0",
            "net_amount": str(amount_dec),
            "provider_transaction_id": resp.transaction_id,
            "latency_ms": resp.latency_ms,
            "error_message": resp.error_message,
            "execution_completed_at": datetime.now(timezone.utc).isoformat(),
        }

        if resp.success:
            action.status = "EXECUTED"
            action.outcome = "RETRY_DISPATCHED"
            action.action_metadata = meta

            # Record gateway PaymentAttempt (status="INITIATED")
            if case.payment_id:
                existing_attempts = (
                    db.query(PaymentAttempt)
                    .filter(PaymentAttempt.payment_id == case.payment_id)
                    .count()
                )
                attempt_record = PaymentAttempt(
                    payment_id=case.payment_id,
                    attempt_number=existing_attempts + 1,
                    status="INITIATED",
                    failure_reason=None,
                    gateway="razorpay" if provider.__class__.__name__ == "RazorpayPaymentProvider" else "mock",
                    payment_method="gateway_retry",
                    timestamp=datetime.now(timezone.utc),
                )
                db.add(attempt_record)

            # State machine transition
            if PaymentStateMachine.can_transition(case.status, "RECOVERY_ACTIVE"):
                case.status = PaymentStateMachine.transition(case.status, "RECOVERY_ACTIVE")

            self._log_audit(
                db=db,
                case_id=case.id,
                event="ACTION_EXECUTED_RETRY",
                previous_state=start_state,
                new_state=case.status,
                reason=f"Gateway retry dispatched successfully. Provider TxID: {resp.transaction_id}",
                metadata=meta,
            )
        else:
            action.status = "FAILED"
            action.outcome = "RETRY_FAILED"
            action.action_metadata = meta

            self._log_audit(
                db=db,
                case_id=case.id,
                event="ACTION_FAILED_RETRY",
                previous_state=start_state,
                new_state=case.status,
                reason=f"Gateway retry failed: {resp.error_message}",
                metadata=meta,
            )

        db.commit()
        db.refresh(action)
        return action, resp

    def _execute_payment_link(
        self,
        db: Session,
        action: RecoveryAction,
        case: RecoveryCase,
        agent_decision: AgentDecision,
        provider: PaymentProvider,
    ) -> Tuple[RecoveryAction, PaymentLinkResponse]:
        """Handle INSTANT_PAYMENT_LINK and DISCOUNTED_PAYMENT_LINK_* executions."""
        start_state = case.status

        # Financial Decimal math
        amount_dec = Decimal(str(case.amount_at_risk))
        discount_pct_map = {
            ActionType.INSTANT_PAYMENT_LINK.value: Decimal("0.0"),
            ActionType.DISCOUNTED_PAYMENT_LINK_5.value: Decimal("5.0"),
            ActionType.DISCOUNTED_PAYMENT_LINK_10.value: Decimal("10.0"),
        }
        discount_pct = discount_pct_map.get(action.action_type, Decimal("0.0"))

        net_amount_dec = (amount_dec * (Decimal("1") - discount_pct / Decimal("100"))).quantize(Decimal("0.01"))

        customer_details = {
            "name": f"Customer_{case.customer_id}",
            "email": case.customer.external_customer_id if case.customer else f"customer_{case.customer_id}@example.com",
            "phone": "+919999999999",
        }
        desc = f"RecoverAI Payment Link for Order #{case.order_id or case.id}"
        if discount_pct > Decimal("0.0"):
            desc += f" ({discount_pct}% Merchant Discount Applied)"

        # Invoke provider API
        link_resp = provider.create_payment_link(
            amount=net_amount_dec,
            original_amount=amount_dec,
            discount_percent=discount_pct,
            description=desc,
            customer_details=customer_details,
            idempotency_key=action.idempotency_key,
            expires_in_hours=24,
        )

        action.executed_at = datetime.now(timezone.utc)
        action.provider_transaction_id = link_resp.link_id

        meta = {
            **(action.action_metadata or {}),
            "provider_link_id": link_resp.link_id,
            "short_url": link_resp.short_url,
            "original_amount": str(amount_dec),
            "discount_pct": str(discount_pct),
            "net_amount": str(net_amount_dec),
            "latency_ms": link_resp.latency_ms,
            "error_message": link_resp.error_message,
            "execution_completed_at": datetime.now(timezone.utc).isoformat(),
        }

        if link_resp.success:
            action.status = "EXECUTED"
            action.outcome = "LINK_CREATED"
            action.action_metadata = meta

            # Downstream notification dispatch (STRICTLY AFTER successful link creation)
            customer_pref_channel = "email"
            if case.customer and hasattr(case.customer, "preferred_channel") and case.customer.preferred_channel:
                customer_pref_channel = case.customer.preferred_channel

            notif = NotificationEvent(
                customer_id=case.customer_id,
                recovery_case_id=case.id,
                channel=customer_pref_channel,
                notification_type="PAYMENT_LINK",
                delivery_status="SENT",
                timestamp=datetime.now(timezone.utc),
            )
            db.add(notif)

            # State machine transition
            if PaymentStateMachine.can_transition(case.status, "RECOVERY_ACTIVE"):
                case.status = PaymentStateMachine.transition(case.status, "RECOVERY_ACTIVE")

            self._log_audit(
                db=db,
                case_id=case.id,
                event="ACTION_EXECUTED_PAYMENT_LINK",
                previous_state=start_state,
                new_state=case.status,
                reason=f"Payment link created successfully. Link ID: {link_resp.link_id}, Short URL: {link_resp.short_url}",
                metadata=meta,
            )
        else:
            action.status = "FAILED"
            action.outcome = "LINK_FAILED"
            action.action_metadata = meta

            self._log_audit(
                db=db,
                case_id=case.id,
                event="ACTION_FAILED_PAYMENT_LINK",
                previous_state=start_state,
                new_state=case.status,
                reason=f"Payment link creation failed: {link_resp.error_message}",
                metadata=meta,
            )

        db.commit()
        db.refresh(action)
        return action, link_resp

    def _execute_manual_review(
        self,
        db: Session,
        action: RecoveryAction,
        case: RecoveryCase,
        agent_decision: AgentDecision,
    ) -> Tuple[RecoveryAction, Dict[str, Any]]:
        """Handle MANUAL_REVIEW execution."""
        start_state = case.status
        action.status = "EXECUTED"
        action.executed_at = datetime.now(timezone.utc)
        action.outcome = "ROUTED_TO_REVIEW"

        meta = {
            **(action.action_metadata or {}),
            "original_amount": str(Decimal(str(case.amount_at_risk))),
            "discount_pct": "0.0",
            "net_amount": str(Decimal(str(case.amount_at_risk))),
            "review_queue": "high_value_manual_review",
            "execution_completed_at": datetime.now(timezone.utc).isoformat(),
        }
        action.action_metadata = meta

        # State machine transition
        if PaymentStateMachine.can_transition(case.status, "RECOVERY_ACTIVE"):
            case.status = PaymentStateMachine.transition(case.status, "RECOVERY_ACTIVE")

        self._log_audit(
            db=db,
            case_id=case.id,
            event="ACTION_EXECUTED_MANUAL_REVIEW",
            previous_state=start_state,
            new_state=case.status,
            reason=f"Case routed to manual review queue based on decision {agent_decision.id}",
            metadata=meta,
        )

        db.commit()
        db.refresh(action)
        return action, {"status": "EXECUTED", "outcome": "ROUTED_TO_REVIEW"}

        self._log_audit(
            db=db,
            case_id=case.id,
            event="ACTION_EXECUTED_MANUAL_REVIEW",
            previous_state=start_state,
            new_state=case.status,
            reason=f"Case routed to manual review queue based on decision {agent_decision.id}",
            metadata=meta,
        )

        db.commit()
        db.refresh(action)
        return action, {"status": "EXECUTED", "outcome": "ROUTED_TO_REVIEW"}

    # -------------------------------------------------------------------------
    # Reconciliation & Auditing Helpers
    # -------------------------------------------------------------------------

    def _reconcile_stale_execution(
        self,
        db: Session,
        action: RecoveryAction,
        case: RecoveryCase,
        provider: PaymentProvider,
    ) -> Tuple[RecoveryAction, Any]:
        """Reconcile a stale EXECUTING action (> 30s) by querying the provider."""
        action_type = action.action_type
        meta = action.action_metadata or {}
        link_id = meta.get("provider_link_id")
        tx_id = action.provider_transaction_id

        if action_type in (
            ActionType.INSTANT_PAYMENT_LINK.value,
            ActionType.DISCOUNTED_PAYMENT_LINK_5.value,
            ActionType.DISCOUNTED_PAYMENT_LINK_10.value,
        ) and link_id:
            status_resp = provider.get_link_status(link_id)
            if status_resp.success:
                action.status = "EXECUTED"
                action.outcome = "RECONCILED_LINK_CREATED"
                db.commit()
                return action, status_resp

        elif action_type == ActionType.RETRY.value and tx_id:
            status_resp = provider.get_payment_status(tx_id)
            if status_resp.success:
                action.status = "EXECUTED"
                action.outcome = "RECONCILED_RETRY_DISPATCHED"
                db.commit()
                return action, status_resp

        # Default fallback if provider query does not resolve: mark RETRYABLE / FAILED
        action.status = "FAILED"
        action.outcome = "STALE_EXECUTION_TIMED_OUT"
        db.commit()
        return action, {"status": "FAILED", "outcome": "STALE_EXECUTION_TIMED_OUT"}

    def _log_audit(
        self,
        db: Session,
        case_id: int,
        event: str,
        previous_state: str,
        new_state: str,
        reason: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Record system AuditLog entry."""
        audit_entry = AuditLog(
            case_id=case_id,
            actor="action_executor",
            event=event,
            previous_state=previous_state,
            new_state=new_state,
            reason=reason,
            timestamp=datetime.now(timezone.utc),
        )
        db.add(audit_entry)
