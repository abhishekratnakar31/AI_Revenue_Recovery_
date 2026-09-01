import os
import pytest
from unittest.mock import MagicMock
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError
from fastapi.testclient import TestClient

# Set test environment
os.environ["USE_TEST_DB"] = "1"
os.environ["TEST_DATABASE_URL"] = "sqlite:///./test.db"

from backend.app.core.config import settings
from backend.app.core.database import Base, get_db
from backend.app.models.models import (
    Customer, Order, Payment, PaymentAttempt, Subscription, RecoveryCase,
    RecoveryAction, ModelPrediction, AgentDecision, PolicyDecision, WebhookEvent,
    NotificationEvent, AuditLog, Experiment, ExperimentAssignment, Outcome, MerchantPolicy
)
from backend.app.main import app

# Test database engine
engine = create_engine("sqlite:///./test.db", connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def test_settings_loaded():
    assert settings.PROJECT_NAME == "RecoverAI"
    assert settings.DEFAULT_MAX_RETRIES == 2
    assert settings.DEFAULT_MANUAL_APPROVAL_THRESHOLD == 25000.0


def test_fastapi_root_endpoint():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["project"] == "RecoverAI"
    assert data["status"] == "running"


def test_fastapi_health_endpoint():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"


def test_fastapi_health_degraded():
    """Test health endpoint behavior when DB throws an error."""
    mock_db = MagicMock()
    mock_db.execute.side_effect = Exception("DB Connection Lost")

    def mock_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = mock_get_db
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert "error: DB Connection Lost" in data["database"]

    # Restore override
    app.dependency_overrides[get_db] = override_get_db


def test_models_crud_and_relationships():
    db = TestingSessionLocal()
    
    # Create Customer
    cust = Customer(external_customer_id="cust_rel_01", customer_segment="vip", lifetime_value=75000.0)
    db.add(cust)
    db.commit()
    db.refresh(cust)

    # Create Order linked to Customer
    order = Order(razorpay_order_id="order_rel_01", customer_id=cust.id, amount=12000.0)
    db.add(order)
    db.commit()
    db.refresh(order)

    # Create Payment linked to Order
    payment = Payment(razorpay_payment_id="pay_rel_01", order_id=order.id, amount=12000.0, status="failed", payment_method="upi")
    db.add(payment)
    db.commit()
    db.refresh(payment)

    # Create PaymentAttempt linked to Payment
    attempt = PaymentAttempt(payment_id=payment.id, attempt_number=1, status="failed", failure_reason="bank_degradation", gateway="upi_bank_x")
    db.add(attempt)
    db.commit()

    # Create RecoveryCase linked to Customer, Order, Payment
    case = RecoveryCase(case_type="payment_failure", customer_id=cust.id, order_id=order.id, payment_id=payment.id, amount_at_risk=12000.0)
    db.add(case)
    db.commit()
    db.refresh(case)

    # Add RecoveryAction
    action = RecoveryAction(recovery_case_id=case.id, action_type="PAYMENT_LINK", idempotency_key="ik_rel_001", expected_net_value=11000.0)
    db.add(action)

    # Add ModelPrediction
    pred = ModelPrediction(recovery_case_id=case.id, model_name="xgboost", model_version="v1.0", prediction=0.92, feature_version="f1")
    db.add(pred)

    # Add AgentDecision
    agent_dec = AgentDecision(recovery_case_id=case.id, selected_action="PAYMENT_LINK", diagnosis_summary="UPI degradation", confidence=0.95)
    db.add(agent_dec)

    # Add PolicyDecision
    pol_dec = PolicyDecision(recovery_case_id=case.id, action_type="PAYMENT_LINK", decision="ALLOW", reason="Allowed by policy")
    db.add(pol_dec)

    # Add NotificationEvent
    notif = NotificationEvent(customer_id=cust.id, recovery_case_id=case.id, channel="sms", notification_type="payment_link")
    db.add(notif)

    # Add Outcome
    outcome = Outcome(case_id=case.id, intervention="PAYMENT_LINK", payment_success=True, gross_recovered=12000.0, net_recovered=11900.0, attribution_status="DIRECT")
    db.add(outcome)
    db.commit()

    # Test Relationship Navigation from Customer down
    saved_cust = db.query(Customer).filter_by(id=cust.id).first()
    assert len(saved_cust.orders) == 1
    assert saved_cust.orders[0].razorpay_order_id == "order_rel_01"
    assert len(saved_cust.orders[0].payments) == 1
    assert saved_cust.orders[0].payments[0].attempts[0].failure_reason == "bank_degradation"
    assert len(saved_cust.recovery_cases) == 1
    assert saved_cust.recovery_cases[0].actions[0].idempotency_key == "ik_rel_001"
    assert saved_cust.recovery_cases[0].predictions[0].prediction == 0.92
    assert saved_cust.recovery_cases[0].agent_decisions[0].selected_action == "PAYMENT_LINK"
    assert saved_cust.recovery_cases[0].policy_decisions[0].decision == "ALLOW"
    assert saved_cust.recovery_cases[0].notifications[0].channel == "sms"
    assert saved_cust.recovery_cases[0].outcome.net_recovered == 11900.0

    db.close()


def test_merchant_policy_defaults():
    db = TestingSessionLocal()
    policy = MerchantPolicy()
    db.add(policy)
    db.commit()
    db.refresh(policy)

    assert policy.max_retries == 2
    assert policy.minimum_retry_interval == 30
    assert policy.max_notifications_per_24h == 2
    assert policy.manual_approval_threshold == 25000.0
    assert policy.max_discount_percentage == 10.0
    assert policy.degradation_pause_enabled is True
    db.close()


def test_unique_constraints_all_entities():
    db = TestingSessionLocal()

    # 1. Customer external_customer_id uniqueness
    c1 = Customer(external_customer_id="cust_unique_01")
    c2 = Customer(external_customer_id="cust_unique_01")
    db.add(c1)
    db.commit()
    db.add(c2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    # 2. Order razorpay_order_id uniqueness
    cust = Customer(external_customer_id="cust_for_order_test")
    db.add(cust)
    db.commit()
    o1 = Order(razorpay_order_id="ord_uniq_01", customer_id=cust.id, amount=100.0)
    o2 = Order(razorpay_order_id="ord_uniq_01", customer_id=cust.id, amount=200.0)
    db.add(o1)
    db.commit()
    db.add(o2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    # 3. Payment razorpay_payment_id uniqueness
    p1 = Payment(razorpay_payment_id="pay_uniq_01", order_id=o1.id, amount=100.0, status="failed")
    p2 = Payment(razorpay_payment_id="pay_uniq_01", order_id=o1.id, amount=100.0, status="failed")
    db.add(p1)
    db.commit()
    db.add(p2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    # 4. RecoveryAction idempotency_key uniqueness
    case = RecoveryCase(case_type="payment_failure", customer_id=cust.id, amount_at_risk=100.0)
    db.add(case)
    db.commit()
    a1 = RecoveryAction(recovery_case_id=case.id, action_type="RETRY", idempotency_key="dup_ik_1")
    a2 = RecoveryAction(recovery_case_id=case.id, action_type="RETRY", idempotency_key="dup_ik_1")
    db.add(a1)
    db.commit()
    db.add(a2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    # 5. Outcome case_id uniqueness
    out1 = Outcome(case_id=case.id, intervention="RETRY")
    out2 = Outcome(case_id=case.id, intervention="PAYMENT_LINK")
    db.add(out1)
    db.commit()
    db.add(out2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    db.close()


def test_database_get_db_generator():
    db_gen = get_db()
    db = next(db_gen)
    assert db is not None
    # Ensure session can execute query
    result = db.execute(text("SELECT 1")).scalar()
    assert result == 1
    # Close generator
    with pytest.raises(StopIteration):
        next(db_gen)
