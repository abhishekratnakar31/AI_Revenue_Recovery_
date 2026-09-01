import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text, UniqueConstraint, JSON
)
from sqlalchemy.orm import relationship
from backend.app.core.database import Base


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    external_customer_id = Column(String(255), unique=True, index=True, nullable=False)
    customer_segment = Column(String(100), default="standard")
    lifetime_value = Column(Float, default=0.0)
    successful_payment_count = Column(Integer, default=0)
    failed_payment_count = Column(Integer, default=0)
    opt_out = Column(Boolean, default=False)
    communication_consent = Column(Boolean, default=True)
    preferred_channel = Column(String(50), default="email")
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    orders = relationship("Order", back_populates="customer")
    subscriptions = relationship("Subscription", back_populates="customer")
    recovery_cases = relationship("RecoveryCase", back_populates="customer")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    razorpay_order_id = Column(String(255), unique=True, index=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), default="INR")
    status = Column(String(50), default="created")
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

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
    status = Column(String(50), nullable=False)
    payment_method = Column(String(50), nullable=True)
    captured_at = Column(DateTime, nullable=True)
    refunded_amount = Column(Float, default=0.0)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    order = relationship("Order", back_populates="payments")
    attempts = relationship("PaymentAttempt", back_populates="payment")
    recovery_cases = relationship("RecoveryCase", back_populates="payment")


class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"

    id = Column(Integer, primary_key=True, index=True)
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=False)
    attempt_number = Column(Integer, default=1)
    status = Column(String(50), nullable=False)
    failure_reason = Column(String(255), nullable=True)
    gateway = Column(String(100), nullable=True)
    bank = Column(String(100), nullable=True)
    payment_method = Column(String(50), nullable=True)
    timestamp = Column(DateTime, default=utc_now)

    payment = relationship("Payment", back_populates="attempts")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    external_subscription_id = Column(String(255), unique=True, index=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    amount = Column(Float, nullable=False)
    billing_interval = Column(String(50), default="monthly")
    status = Column(String(50), default="active")
    renewal_date = Column(DateTime, nullable=True)
    failed_renewal_count = Column(Integer, default=0)

    customer = relationship("Customer", back_populates="subscriptions")
    recovery_cases = relationship("RecoveryCase", back_populates="subscription")


class RecoveryCase(Base):
    __tablename__ = "recovery_cases"

    id = Column(Integer, primary_key=True, index=True)
    case_type = Column(String(50), nullable=False)  # payment_failure, subscription_renewal
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=True)
    amount_at_risk = Column(Float, nullable=False)
    recoverable_amount_estimate = Column(Float, default=0.0)
    recovery_probability = Column(Float, nullable=True)
    status = Column(String(50), default="PENDING_VERIFICATION")
    attribution_window = Column(Integer, default=72)  # in hours
    created_at = Column(DateTime, default=utc_now)
    closed_at = Column(DateTime, nullable=True)

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
    __tablename__ = "recovery_actions"

    id = Column(Integer, primary_key=True, index=True)
    recovery_case_id = Column(Integer, ForeignKey("recovery_cases.id"), nullable=False)
    action_type = Column(String(50), nullable=False)
    idempotency_key = Column(String(255), unique=True, index=True, nullable=False)
    expected_recovery = Column(Float, default=0.0)
    expected_cost = Column(Float, default=0.0)
    expected_net_value = Column(Float, default=0.0)
    status = Column(String(50), default="SCHEDULED")
    scheduled_at = Column(DateTime, default=utc_now)
    executed_at = Column(DateTime, nullable=True)
    outcome = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=utc_now)

    recovery_case = relationship("RecoveryCase", back_populates="actions")


class ModelPrediction(Base):
    __tablename__ = "model_predictions"

    id = Column(Integer, primary_key=True, index=True)
    recovery_case_id = Column(Integer, ForeignKey("recovery_cases.id"), nullable=False)
    model_name = Column(String(100), nullable=False)
    model_version = Column(String(50), nullable=False)
    prediction = Column(Float, nullable=False)
    feature_version = Column(String(50), nullable=False)
    predicted_at = Column(DateTime, default=utc_now)

    recovery_case = relationship("RecoveryCase", back_populates="predictions")


class AgentDecision(Base):
    __tablename__ = "agent_decisions"

    id = Column(Integer, primary_key=True, index=True)
    recovery_case_id = Column(Integer, ForeignKey("recovery_cases.id"), nullable=False)
    selected_action = Column(String(50), nullable=False)
    diagnosis_summary = Column(Text, nullable=True)
    confidence = Column(Float, default=0.0)
    provider = Column(String(50), default="gemini")
    model_version = Column(String(50), default="v1")
    created_at = Column(DateTime, default=utc_now)

    recovery_case = relationship("RecoveryCase", back_populates="agent_decisions")


class PolicyDecision(Base):
    __tablename__ = "policy_decisions"

    id = Column(Integer, primary_key=True, index=True)
    recovery_case_id = Column(Integer, ForeignKey("recovery_cases.id"), nullable=False)
    action_type = Column(String(50), nullable=False)
    decision = Column(String(50), nullable=False)
    reason = Column(String(255), nullable=True)
    policy_version = Column(String(50), default="v1")
    created_at = Column(DateTime, default=utc_now)

    recovery_case = relationship("RecoveryCase", back_populates="policy_decisions")


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id = Column(Integer, primary_key=True, index=True)
    razorpay_event_id = Column(String(255), unique=True, index=True, nullable=False)
    event_type = Column(String(100), nullable=False)
    payload_hash = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False)
    received_at = Column(DateTime, default=utc_now)
    processed_at = Column(DateTime, nullable=True)
    processing_status = Column(String(50), default="RECEIVED")


class NotificationEvent(Base):
    __tablename__ = "notification_events"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    recovery_case_id = Column(Integer, ForeignKey("recovery_cases.id"), nullable=False)
    channel = Column(String(50), nullable=False)
    notification_type = Column(String(50), nullable=False)
    timestamp = Column(DateTime, default=utc_now)
    delivery_status = Column(String(50), default="SENT")

    recovery_case = relationship("RecoveryCase", back_populates="notifications")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, nullable=True, index=True)
    actor = Column(String(100), default="system")
    event = Column(String(100), nullable=False)
    previous_state = Column(String(50), nullable=True)
    new_state = Column(String(50), nullable=True)
    reason = Column(Text, nullable=True)
    model_version = Column(String(50), nullable=True)
    policy_version = Column(String(50), nullable=True)
    timestamp = Column(DateTime, default=utc_now)


class Experiment(Base):
    __tablename__ = "experiments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    dataset_version = Column(String(50), nullable=False)
    random_seed = Column(Integer, default=42)
    configuration = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utc_now)


class ExperimentAssignment(Base):
    __tablename__ = "experiment_assignments"

    id = Column(Integer, primary_key=True, index=True)
    experiment_id = Column(Integer, ForeignKey("experiments.id"), nullable=False)
    case_id = Column(Integer, ForeignKey("recovery_cases.id"), nullable=False)
    group = Column(String(50), nullable=False)
    assigned_at = Column(DateTime, default=utc_now)


class Outcome(Base):
    __tablename__ = "outcomes"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("recovery_cases.id"), unique=True, nullable=False)
    intervention = Column(String(50), nullable=False)
    payment_success = Column(Boolean, default=False)
    gross_recovered = Column(Float, default=0.0)
    refund_amount = Column(Float, default=0.0)
    net_recovered = Column(Float, default=0.0)
    attribution_status = Column(String(50), default="UNKNOWN")
    recovery_timestamp = Column(DateTime, nullable=True)

    recovery_case = relationship("RecoveryCase", back_populates="outcome")


class MerchantPolicy(Base):
    __tablename__ = "merchant_policies"

    id = Column(Integer, primary_key=True, index=True)
    max_retries = Column(Integer, default=2)
    minimum_retry_interval = Column(Integer, default=30)
    max_notifications_per_24h = Column(Integer, default=2)
    manual_approval_threshold = Column(Float, default=25000.0)
    max_discount_percentage = Column(Float, default=10.0)
    degradation_pause_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
