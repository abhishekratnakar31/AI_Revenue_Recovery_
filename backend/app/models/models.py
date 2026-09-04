"""
Database Models Module

This module defines all 16 core PostgreSQL relational database entities using SQLAlchemy ORM.
These tables serve as the single source of truth for the RecoverAI platform:

Domain Models Defined:
 1. Customer: Merchant customer profiles, lifetime value (CLV), failure counts, opt-out status.
 2. Order: Merchant e-commerce order details and statuses.
 3. Payment: Main transaction attempts, amounts, payment methods, captured timestamps.
 4. PaymentAttempt: Granular gateway attempts, failure reasons, banks, payment methods.
 5. Subscription: Recurring subscription contracts, billing intervals, renewal failures.
 6. RecoveryCase: Central risk event tracking record, state, amount at risk, probability.
 7. RecoveryAction: Executed recovery interventions (Retries, Payment Links) with idempotency keys.
 8. ModelPrediction: Audit log of predictive ML probability outputs (P(recovery)).
 9. AgentDecision: LLM diagnosis summaries, selected candidate actions, confidence scores.
10. PolicyDecision: Deterministic policy gateway decisions (ALLOW, BLOCK, REVIEW).
11. WebhookEvent: Incoming raw Razorpay webhook events with UNIQUE(razorpay_event_id).
12. NotificationEvent: Audit trail of sent customer communications (email/SMS/WhatsApp).
13. AuditLog: Chronological audit trail tracking state transitions, actors, and reasons.
14. Experiment: A/B testing experiment definitions and configurations.
15. ExperimentAssignment: Randomized assignment of cases to CONTROL, TREATMENT, or NO_INTERVENTION.
16. Outcome: Final recovery performance metrics, gross/net revenue, refund tracking, attribution status.
17. MerchantPolicy: Configurable merchant policies (max retries, retry intervals, approval limits).
"""

import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text, UniqueConstraint, JSON
)
from sqlalchemy.orm import relationship
from backend.app.core.database import Base


def utc_now():
    """Returns the current timezone-aware UTC datetime."""
    return datetime.datetime.now(datetime.timezone.utc)


class Customer(Base):
    """
    Represents a merchant's customer profile.
    Stores historical payment behavior, lifetime value, communication preferences, and opt-out status.
    """
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    external_customer_id = Column(String(255), unique=True, index=True, nullable=False)
    customer_segment = Column(String(100), default="standard")  # e.g., standard, vip, high_value
    lifetime_value = Column(Float, default=0.0)
    successful_payment_count = Column(Integer, default=0)
    failed_payment_count = Column(Integer, default=0)
    opt_out = Column(Boolean, default=False)  # If True, no recovery messages can be sent
    communication_consent = Column(Boolean, default=True)
    preferred_channel = Column(String(50), default="email")  # email, sms, whatsapp
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    orders = relationship("Order", back_populates="customer")
    subscriptions = relationship("Subscription", back_populates="customer")
    recovery_cases = relationship("RecoveryCase", back_populates="customer")


class Order(Base):
    """
    Represents an e-commerce order created on the merchant platform.
    Linked to Razorpay's razorpay_order_id.
    """
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    razorpay_order_id = Column(String(255), unique=True, index=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    amount = Column(Float, nullable=False)  # Order value in INR
    currency = Column(String(10), default="INR")
    status = Column(String(50), default="created")  # created, paid, failed
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    customer = relationship("Customer", back_populates="orders")
    payments = relationship("Payment", back_populates="order")
    recovery_cases = relationship("RecoveryCase", back_populates="order")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    razorpay_payment_id = Column(String(255), unique=True, index=True, nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), default="INR")
    status = Column(String(50), nullable=False)  # created, authorized, captured, failed
    payment_method = Column(String(50), nullable=True)  # card, upi, netbanking, wallet
    captured_at = Column(DateTime, nullable=True)
    refunded_amount = Column(Float, default=0.0)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    order = relationship("Order", back_populates="payments")
    attempts = relationship("PaymentAttempt", back_populates="payment")
    recovery_cases = relationship("RecoveryCase", back_populates="payment")


class PaymentAttempt(Base):
    """
    Represents an individual payment attempt at the gateway layer.
    A single order/payment may have multiple attempts (e.g. attempt #1 failed, attempt #2 succeeded).
    """
    __tablename__ = "payment_attempts"

    id = Column(Integer, primary_key=True, index=True)
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=False)
    attempt_number = Column(Integer, default=1)
    status = Column(String(50), nullable=False)  # failed, captured
    failure_reason = Column(String(255), nullable=True)  # bank_timeout, insufficient_funds, etc.
    gateway = Column(String(100), nullable=True)
    bank = Column(String(100), nullable=True)
    payment_method = Column(String(50), nullable=True)
    timestamp = Column(DateTime, default=utc_now)

    payment = relationship("Payment", back_populates="attempts")


class Subscription(Base):
    """
    Represents a recurring subscription contract.
    Used for failed recurring renewal tracking and recovery.
    """
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    external_subscription_id = Column(String(255), unique=True, index=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    amount = Column(Float, nullable=False)
    billing_interval = Column(String(50), default="monthly")
    status = Column(String(50), default="active")  # active, pending, cancelled
    renewal_date = Column(DateTime, nullable=True)
    failed_renewal_count = Column(Integer, default=0)

    # Relationships
    customer = relationship("Customer", back_populates="subscriptions")
    recovery_cases = relationship("RecoveryCase", back_populates="subscription")


class RecoveryCase(Base):
    """
    The central entity representing a revenue risk event being tracked by RecoverAI.
    Aggregates payment attempts for an order and manages state machine progression.
    """
    __tablename__ = "recovery_cases"

    id = Column(Integer, primary_key=True, index=True)
    case_type = Column(String(50), nullable=False)  # payment_failure, subscription_renewal
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=True)
    amount_at_risk = Column(Float, nullable=False)
    recoverable_amount_estimate = Column(Float, default=0.0)
    recovery_probability = Column(Float, nullable=True)  # P(recovery) score from ML model
    status = Column(String(50), default="PENDING_VERIFICATION")  # Managed by PaymentStateMachine
    attribution_window = Column(Integer, default=72)  # Configurable attribution window in hours
    created_at = Column(DateTime, default=utc_now)
    closed_at = Column(DateTime, nullable=True)

    # Relationships
    customer = relationship("Customer", back_populates="recovery_cases")
    order = relationship("Order", back_populates="recovery_cases")
    payment = relationship("Payment", back_populates="recovery_cases")
    subscription = relationship("Subscription", back_populates="recovery_cases")
    actions = relationship("RecoveryAction", back_populates="recovery_case")
    predictions = relationship("ModelPrediction", back_populates="recovery_case")
    agent_decisions = relationship("AgentDecision", back_populates="recovery_case")
    policy_decisions = relationship("PolicyDecision", back_populates="recovery_case")
    notifications = relationship("NotificationEvent", back_populates="recovery_case")
    outcome = relationship("Outcome", back_populates="recovery_case", uselist=False)


class RecoveryAction(Base):
    """
    Represents an intervention action executed by RecoverAI (e.g. RETRY, PAYMENT_LINK, EMAIL_REMINDER).
    Uses database-level UNIQUE(idempotency_key) to prevent double execution.
    """
    __tablename__ = "recovery_actions"

    id = Column(Integer, primary_key=True, index=True)
    recovery_case_id = Column(Integer, ForeignKey("recovery_cases.id"), nullable=False)
    action_type = Column(String(50), nullable=False)  # RETRY, PAYMENT_LINK, EMAIL_REMINDER, etc.
    idempotency_key = Column(String(255), unique=True, index=True, nullable=False)
    expected_recovery = Column(Float, default=0.0)
    expected_cost = Column(Float, default=0.0)
    expected_net_value = Column(Float, default=0.0)
    status = Column(String(50), default="CREATED")  # CREATED, EXECUTING, EXECUTED, FAILED, RETRYABLE, TERMINAL
    scheduled_at = Column(DateTime, default=utc_now)
    executed_at = Column(DateTime, nullable=True)
    outcome = Column(String(50), nullable=True)
    provider = Column(String(50), nullable=True)  # mock, razorpay
    provider_transaction_id = Column(String(255), nullable=True)
    action_metadata = Column(JSON, nullable=True)  # provider_link_id, original_amount, discount_pct, net_amount, etc.
    created_at = Column(DateTime, default=utc_now)

    recovery_case = relationship("RecoveryCase", back_populates="actions")


class ModelPrediction(Base):
    """
    Audit log of predictive ML probability outputs generated for a recovery case.
    Tracks model versioning and feature schema versioning for reproducible benchmarks.
    """
    __tablename__ = "model_predictions"

    id = Column(Integer, primary_key=True, index=True)
    recovery_case_id = Column(Integer, ForeignKey("recovery_cases.id"), nullable=False)
    model_name = Column(String(100), nullable=False)  # e.g., xgboost_recovery
    model_version = Column(String(50), nullable=False)  # e.g., v1.0
    prediction = Column(Float, nullable=False)  # Calibrated P(recovery) probability [0.0 - 1.0]
    feature_version = Column(String(50), nullable=False)
    predicted_at = Column(DateTime, default=utc_now)

    recovery_case = relationship("RecoveryCase", back_populates="predictions")


class AgentDecision(Base):
    """
    Stores reasoning outputs generated by the Gemini AI Decision Agent.
    Note: Does NOT store hidden chain-of-thought, only structured diagnosis and recommendations.
    """
    __tablename__ = "agent_decisions"
    __table_args__ = (
        UniqueConstraint("recovery_case_id", "model_name", name="uq_agent_decision_case_model"),
    )

    id = Column(Integer, primary_key=True, index=True)
    recovery_case_id = Column(Integer, ForeignKey("recovery_cases.id"), nullable=False)
    selected_action = Column(String(50), nullable=False)
    diagnosis_summary = Column(Text, nullable=True)
    confidence = Column(Float, default=0.0)
    confidence_score = Column(Float, default=0.0)
    provider = Column(String(50), default="gemini")  # gemini, mock
    model_name = Column(String(100), default="ENV_Engine_env_v1")
    model_version = Column(String(50), default="v1")
    reasoning = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    recovery_case = relationship("RecoveryCase", back_populates="agent_decisions")


class PolicyDecision(Base):
    """
    Stores decisions made by the Deterministic Policy Engine.
    Tracks whether a candidate action was ALLOWED, BLOCKED, or flagged for REVIEW.
    """
    __tablename__ = "policy_decisions"

    id = Column(Integer, primary_key=True, index=True)
    recovery_case_id = Column(Integer, ForeignKey("recovery_cases.id"), nullable=False)
    action_type = Column(String(50), nullable=False)
    decision = Column(String(50), nullable=False)  # ALLOW, BLOCK, REVIEW
    reason = Column(String(255), nullable=True)
    policy_version = Column(String(50), default="v1")
    created_at = Column(DateTime, default=utc_now)

    recovery_case = relationship("RecoveryCase", back_populates="policy_decisions")


class WebhookEvent(Base):
    """
    Stores incoming raw webhook events from Razorpay.
    Enforces atomic idempotency via database-level UNIQUE constraint on razorpay_event_id.
    """
    __tablename__ = "webhook_events"

    id = Column(Integer, primary_key=True, index=True)
    razorpay_event_id = Column(String(255), unique=True, index=True, nullable=False)
    event_type = Column(String(100), nullable=False)  # payment.failed, payment.captured, etc.
    payload_hash = Column(String(64), nullable=False)  # SHA-256 hash of raw request body
    payload = Column(JSON, nullable=False)
    received_at = Column(DateTime, default=utc_now)
    processed_at = Column(DateTime, nullable=True)
    processing_status = Column(String(50), default="RECEIVED")  # RECEIVED, PROCESSED, FAILED


class NotificationEvent(Base):
    """
    Audit log of customer notifications dispatched across channels (Email, SMS, WhatsApp).
    """
    __tablename__ = "notification_events"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    recovery_case_id = Column(Integer, ForeignKey("recovery_cases.id"), nullable=False)
    channel = Column(String(50), nullable=False)  # email, sms, whatsapp
    notification_type = Column(String(50), nullable=False)
    timestamp = Column(DateTime, default=utc_now)
    delivery_status = Column(String(50), default="SENT")

    recovery_case = relationship("RecoveryCase", back_populates="notifications")


class AuditLog(Base):
    """
    System-wide audit trail recording state transitions, policy checks, actors, and reasons.
    Enables complete operational auditability for merchants and compliance.
    """
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, nullable=True, index=True)
    actor = Column(String(100), default="system")  # system, merchant, agent
    event = Column(String(100), nullable=False)
    previous_state = Column(String(50), nullable=True)
    new_state = Column(String(50), nullable=True)
    reason = Column(Text, nullable=True)
    model_version = Column(String(50), nullable=True)
    policy_version = Column(String(50), nullable=True)
    timestamp = Column(DateTime, default=utc_now)


class Experiment(Base):
    """
    Defines A/B testing experiment configurations.
    Used for randomized control/treatment experiments measuring incremental recovery lift.
    """
    __tablename__ = "experiments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    dataset_version = Column(String(50), nullable=False)
    random_seed = Column(Integer, default=42)
    configuration = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utc_now)


class ExperimentAssignment(Base):
    """
    Records case assignments to experiment groups (CONTROL, TREATMENT, or NO_INTERVENTION).
    """
    __tablename__ = "experiment_assignments"

    id = Column(Integer, primary_key=True, index=True)
    experiment_id = Column(Integer, ForeignKey("experiments.id"), nullable=False)
    case_id = Column(Integer, ForeignKey("recovery_cases.id"), nullable=False)
    group = Column(String(50), nullable=False)  # CONTROL, TREATMENT, NO_INTERVENTION
    assigned_at = Column(DateTime, default=utc_now)


class Outcome(Base):
    """
    Stores final financial outcomes for a recovery case.
    Tracks gross revenue, refunds, net recovered revenue, and recovery attribution status.
    """
    __tablename__ = "outcomes"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("recovery_cases.id"), unique=True, nullable=False)
    intervention = Column(String(50), nullable=False)  # Retry, Payment Link, Natural Capture, etc.
    payment_success = Column(Boolean, default=False)
    gross_recovered = Column(Float, default=0.0)
    refund_amount = Column(Float, default=0.0)
    net_recovered = Column(Float, default=0.0)
    attribution_status = Column(String(50), default="UNKNOWN")  # DIRECT, NATURAL_RECOVERY, UNKNOWN
    recovery_timestamp = Column(DateTime, nullable=True)

    recovery_case = relationship("RecoveryCase", back_populates="outcome")


class MerchantPolicy(Base):
    """
    Configurable merchant policy guardrails.
    Determines maximum retries, retry intervals, approval thresholds, and degradation pause rules.
    """
    __tablename__ = "merchant_policies"

    id = Column(Integer, primary_key=True, index=True)
    max_retries = Column(Integer, default=2)
    minimum_retry_interval = Column(Integer, default=30)  # in minutes
    max_notifications_per_24h = Column(Integer, default=2)
    manual_approval_threshold = Column(Float, default=25000.0)  # INR threshold requiring manual approval
    max_discount_percentage = Column(Float, default=10.0)
    degradation_pause_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
