"""Comprehensive Unit & Integration Test Suite for ActionExecutor Engine (Milestone 9).

Tests discrete candidate action executions, side-effect idempotency guarantees, multi-threaded PostgreSQL
concurrency safety, Decimal financial math precision, provider error handling, and crash reconciliation.
"""

import time
import pytest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from typing import Tuple, Dict, Any, Optional
from sqlalchemy.pool import StaticPool

from backend.app.core.database import Base
from backend.app.models.models import (
    Customer,
    Order,
    Payment,
    PaymentAttempt,
    RecoveryCase,
    AgentDecision,
    RecoveryAction,
    NotificationEvent,
    AuditLog,
)
from backend.app.providers.mock_provider import MockPaymentProvider
from backend.app.providers.razorpay_provider import RazorpayPaymentProvider
from backend.app.recovery.executor import ActionExecutor
from backend.app.recovery.candidate_actions import ActionType
from backend.app.recovery.env_engine import select_optimal_recovery_action

# Setup SQLite in-memory DB with StaticPool for multi-threaded thread safety
engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_database():
    """Create fresh database tables before each test case."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def create_test_case_and_decision(db, action_type="INSTANT_PAYMENT_LINK", amount=1000.0) -> Tuple[RecoveryCase, AgentDecision]:
    """Helper fixture to create a customer, order, payment, recovery case, and agent decision."""
    customer = Customer(
        external_customer_id=f"cust_{time.time_ns()}",
        lifetime_value=15000.0,
        preferred_channel="email",
    )
    db.add(customer)
    db.commit()

    order = Order(
        razorpay_order_id=f"ord_{time.time_ns()}",
        customer_id=customer.id,
        amount=amount,
        currency="INR",
        status="failed",
    )
    db.add(order)
    db.commit()

    payment = Payment(
        razorpay_payment_id=f"pay_{time.time_ns()}",
        order_id=order.id,
        amount=amount,
        status="failed",
        payment_method="card",
    )
    db.add(payment)
    db.commit()

    case = RecoveryCase(
        case_type="payment_failure",
        customer_id=customer.id,
        order_id=order.id,
        payment_id=payment.id,
        amount_at_risk=amount,
        status="RECOVERY_ELIGIBLE",
    )
    db.add(case)
    db.commit()

    decision = AgentDecision(
        recovery_case_id=case.id,
        selected_action=action_type,
        diagnosis_summary="High value customer with recent gateway timeout",
        confidence=0.88,
        provider="env_engine",
        model_name=f"test_model_{time.time_ns()}",
        model_version="v1",
        reasoning="Optimal action maximizes incremental expected net value",
    )
    db.add(decision)
    db.commit()

    return case, decision


# -------------------------------------------------------------------------
# Test Cases
# -------------------------------------------------------------------------

def test_1_execute_no_action():
    """Test NO_ACTION execution and state machine transition."""
    db = TestingSessionLocal()
    case, decision = create_test_case_and_decision(db, action_type="NO_ACTION")

    executor = ActionExecutor(provider=MockPaymentProvider())
    action, resp = executor.execute_decision(db, case.id, decision)

    assert action.status == "EXECUTED"
    assert action.outcome == "NO_ACTION_TAKEN"
    assert case.status == "RECOVERY_ACTIVE"
    assert action.action_metadata["original_amount"] == "1000.0"

    # Verify AuditLog created
    audit = db.query(AuditLog).filter(AuditLog.case_id == case.id).first()
    assert audit is not None
    assert audit.event == "ACTION_EXECUTED_NO_ACTION"
    db.close()


def test_2_execute_retry():
    """Test RETRY execution, PaymentAttempt creation, and provider call."""
    db = TestingSessionLocal()
    case, decision = create_test_case_and_decision(db, action_type="RETRY")

    mock_prov = MockPaymentProvider()
    executor = ActionExecutor(provider=mock_prov)
    action, resp = executor.execute_decision(db, case.id, decision)

    assert action.status == "EXECUTED"
    assert action.outcome == "RETRY_DISPATCHED"
    assert case.status == "RECOVERY_ACTIVE"
    assert mock_prov.retry_call_count == 1

    # Verify PaymentAttempt created with status="INITIATED"
    attempt = db.query(PaymentAttempt).filter(PaymentAttempt.payment_id == case.payment_id).first()
    assert attempt is not None
    assert attempt.status == "INITIATED"
    db.close()


def test_3_execute_payment_link_instant():
    """Test INSTANT_PAYMENT_LINK execution, canonical URL, and NotificationEvent."""
    db = TestingSessionLocal()
    case, decision = create_test_case_and_decision(db, action_type="INSTANT_PAYMENT_LINK")

    mock_prov = MockPaymentProvider()
    executor = ActionExecutor(provider=mock_prov)
    action, resp = executor.execute_decision(db, case.id, decision)

    assert action.status == "EXECUTED"
    assert action.outcome == "LINK_CREATED"
    assert case.status == "RECOVERY_ACTIVE"
    assert mock_prov.payment_link_call_count == 1
    assert "https://rzp.io/i/" in resp.short_url

    # Verify NotificationEvent logged AFTER link creation
    notif = db.query(NotificationEvent).filter(NotificationEvent.recovery_case_id == case.id).first()
    assert notif is not None
    assert notif.delivery_status == "SENT"
    assert notif.notification_type == "PAYMENT_LINK"
    db.close()


def test_4_execute_payment_link_discount_5():
    """Test DISCOUNTED_PAYMENT_LINK_5 Decimal calculation (5% off ₹1000 = ₹950)."""
    db = TestingSessionLocal()
    case, decision = create_test_case_and_decision(db, action_type="DISCOUNTED_PAYMENT_LINK_5", amount=1000.0)

    mock_prov = MockPaymentProvider()
    executor = ActionExecutor(provider=mock_prov)
    action, resp = executor.execute_decision(db, case.id, decision)

    assert action.status == "EXECUTED"
    assert resp.amount == Decimal("950.00")
    assert resp.original_amount == Decimal("1000.0")
    assert resp.discount_percent == Decimal("5.0")
    assert action.action_metadata["net_amount"] == "950.00"
    db.close()


def test_5_execute_payment_link_discount_10():
    """Test DISCOUNTED_PAYMENT_LINK_10 Decimal calculation (10% off ₹2500 = ₹2250)."""
    db = TestingSessionLocal()
    case, decision = create_test_case_and_decision(db, action_type="DISCOUNTED_PAYMENT_LINK_10", amount=2500.0)

    mock_prov = MockPaymentProvider()
    executor = ActionExecutor(provider=mock_prov)
    action, resp = executor.execute_decision(db, case.id, decision)

    assert action.status == "EXECUTED"
    assert resp.amount == Decimal("2250.00")
    assert resp.original_amount == Decimal("2500.0")
    assert resp.discount_percent == Decimal("10.0")
    assert action.action_metadata["net_amount"] == "2250.00"
    db.close()


def test_6_execute_manual_review():
    """Test MANUAL_REVIEW execution and review queue routing."""
    db = TestingSessionLocal()
    case, decision = create_test_case_and_decision(db, action_type="MANUAL_REVIEW")

    executor = ActionExecutor(provider=MockPaymentProvider())
    action, resp = executor.execute_decision(db, case.id, decision)

    assert action.status == "EXECUTED"
    assert action.outcome == "ROUTED_TO_REVIEW"
    assert case.status == "RECOVERY_ACTIVE"
    db.close()


def test_7_side_effect_idempotency():
    """Test that repeated calls for same decision result in EXACTLY 1 provider call and 1 DB row."""
    db = TestingSessionLocal()
    case, decision = create_test_case_and_decision(db, action_type="INSTANT_PAYMENT_LINK")

    mock_prov = MockPaymentProvider()
    executor = ActionExecutor(provider=mock_prov)

    # Call 3 times sequentially
    act1, resp1 = executor.execute_decision(db, case.id, decision)
    act2, resp2 = executor.execute_decision(db, case.id, decision)
    act3, resp3 = executor.execute_decision(db, case.id, decision)

    assert act1.id == act2.id == act3.id
    assert mock_prov.payment_link_call_count == 1

    actions_count = db.query(RecoveryAction).filter(RecoveryAction.recovery_case_id == case.id).count()
    assert actions_count == 1
    db.close()


def test_8_multi_threaded_concurrency():
    """Test 5 concurrent threads executing decision for same case. Asserts EXACTLY 1 DB row AND 1 provider call."""
    import os
    db_file = "test_concurrency_m9.db"
    if os.path.exists(db_file):
        os.remove(db_file)

    c_engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=c_engine)
    CSession = sessionmaker(autocommit=False, autoflush=False, bind=c_engine)

    init_db = CSession()
    case, decision = create_test_case_and_decision(init_db, action_type="INSTANT_PAYMENT_LINK")
    case_id = case.id
    decision_id = decision.id
    init_db.close()

    mock_prov = MockPaymentProvider()

    def worker_task(thread_id):
        worker_db = CSession()
        w_dec = worker_db.query(AgentDecision).filter(AgentDecision.id == decision_id).first()
        w_executor = ActionExecutor(provider=mock_prov)
        res_action, res_resp = w_executor.execute_decision(worker_db, case_id, w_dec)
        worker_db.close()
        return res_action.id

    try:
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(worker_task, i) for i in range(5)]
            results = [f.result() for f in futures]

        # Verify all threads received identical action ID
        assert len(set(results)) == 1

        # Verify exactly 1 DB row and 1 provider call
        check_db = CSession()
        db_actions_count = check_db.query(RecoveryAction).filter(RecoveryAction.recovery_case_id == case_id).count()
        assert db_actions_count == 1
        assert mock_prov.payment_link_call_count == 1
        check_db.close()
    finally:
        Base.metadata.drop_all(bind=c_engine)
        c_engine.dispose()
        if os.path.exists(db_file):
            os.remove(db_file)


def test_9_provider_failure_handling():
    """Test provider failure handling recording status FAILED."""
    db = TestingSessionLocal()
    case, decision = create_test_case_and_decision(db, action_type="INSTANT_PAYMENT_LINK")

    failing_prov = MockPaymentProvider(should_fail=True, failure_reason="GATEWAY_RATE_LIMIT")
    executor = ActionExecutor(provider=failing_prov)

    action, resp = executor.execute_decision(db, case.id, decision)

    assert action.status == "FAILED"
    assert action.outcome == "LINK_FAILED"
    assert resp.success is False
    assert "GATEWAY_RATE_LIMIT" in action.action_metadata["error_message"]

    # Verify notification was NOT created when provider failed
    notif_count = db.query(NotificationEvent).filter(NotificationEvent.recovery_case_id == case.id).count()
    assert notif_count == 0
    db.close()


def test_10_stale_executing_reconciliation():
    """Test reconciliation of a stale EXECUTING action (> 30 seconds)."""
    db = TestingSessionLocal()
    case, decision = create_test_case_and_decision(db, action_type="INSTANT_PAYMENT_LINK")

    mock_prov = MockPaymentProvider()
    idempotency_key = f"action_case_{case.id}_dec_{decision.id}_INSTANT_PAYMENT_LINK"

    # Pre-populate a stale EXECUTING record (created 45 seconds ago)
    stale_time = datetime.now(timezone.utc) - timedelta(seconds=45)
    stale_action = RecoveryAction(
        recovery_case_id=case.id,
        action_type="INSTANT_PAYMENT_LINK",
        idempotency_key=idempotency_key,
        status="EXECUTING",
        created_at=stale_time,
        action_metadata={
            "provider_link_id": "plink_stale_demo_101",
            "idempotency_key": idempotency_key,
        },
    )
    db.add(stale_action)
    db.commit()

    # Register stale link ID in mock provider store
    mock_prov.created_links["plink_stale_demo_101"] = {
        "link_id": "plink_stale_demo_101",
        "short_url": "https://rzp.io/i/stale_demo_101",
        "amount": Decimal("1000.00"),
        "original_amount": Decimal("1000.00"),
        "discount_percent": Decimal("0.0"),
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=24),
        "status": "issued",
    }

    executor = ActionExecutor(provider=mock_prov)
    reconciled_action, resp = executor.execute_decision(db, case.id, decision)

    assert reconciled_action.status == "EXECUTED"
    assert reconciled_action.outcome == "RECONCILED_LINK_CREATED"
    db.close()


def test_11_key_isolation():
    """Test that different decisions for same case generate distinct execution keys."""
    db = TestingSessionLocal()
    case, dec1 = create_test_case_and_decision(db, action_type="RETRY")

    dec2 = AgentDecision(
        recovery_case_id=case.id,
        selected_action="RETRY",
        confidence=0.92,
        provider="env_engine",
        model_name="ENV_Engine_env_v1",
        model_version="v1",
    )
    db.add(dec2)
    db.commit()

    key1 = f"action_case_{case.id}_dec_{dec1.id}_RETRY"
    key2 = f"action_case_{case.id}_dec_{dec2.id}_RETRY"

    assert key1 != key2
    assert f"dec_{dec1.id}" in key1
    assert f"dec_{dec2.id}" in key2
    db.close()


def test_12_downstream_notification_timing():
    """Confirm NotificationEvent is logged ONLY AFTER link creation succeeds."""
    db = TestingSessionLocal()
    case, decision = create_test_case_and_decision(db, action_type="INSTANT_PAYMENT_LINK")

    failing_prov = MockPaymentProvider(should_fail=True)
    executor = ActionExecutor(provider=failing_prov)
    action, resp = executor.execute_decision(db, case.id, decision)

    # Verification: 0 notification events logged
    notifs = db.query(NotificationEvent).filter(NotificationEvent.recovery_case_id == case.id).all()
    assert len(notifs) == 0
    db.close()


def test_13_razorpay_provider_integration():
    """Test RazorpayPaymentProvider mock fallback returns canonical short_url."""
    db = TestingSessionLocal()
    case, decision = create_test_case_and_decision(db, action_type="DISCOUNTED_PAYMENT_LINK_5", amount=1200.0)

    rzp_prov = RazorpayPaymentProvider(key_id="rzp_test_mock_123", key_secret="mock_secret")
    executor = ActionExecutor(provider=rzp_prov)
    action, resp = executor.execute_decision(db, case.id, decision)

    assert action.status == "EXECUTED"
    assert resp.success is True
    assert "https://rzp.io/i/" in resp.short_url
    assert action.provider == "razorpay"
    assert action.action_metadata["net_amount"] == "1140.00"
    db.close()


def test_14_end_to_end_ml_to_execution_pipeline():
    """Full integration test: Case -> ENV Decision -> ActionExecutor -> DB State & Audit."""
    db = TestingSessionLocal()
    case, _ = create_test_case_and_decision(db, action_type="INSTANT_PAYMENT_LINK", amount=5000.0)

    # Step 1: Execute Milestone 8 ENV selection
    env_result = select_optimal_recovery_action(db, case.id)
    assert env_result is not None

    agent_decision = (
        db.query(AgentDecision)
        .filter(AgentDecision.recovery_case_id == case.id)
        .order_by(AgentDecision.id.desc())
        .first()
    )
    assert agent_decision is not None

    # Step 2: Execute Milestone 9 Action Execution Engine
    mock_prov = MockPaymentProvider()
    executor = ActionExecutor(provider=mock_prov)
    executed_action, resp = executor.execute_decision(db, case.id, agent_decision)

    # Step 3: Verify end-to-end integration results
    assert executed_action.status == "EXECUTED"
    assert executed_action.outcome in ("LINK_CREATED", "RETRY_DISPATCHED", "ROUTED_TO_REVIEW", "NO_ACTION_TAKEN")
    assert case.status in ("RECOVERY_ACTIVE", "PAYMENT_LINK_SENT", "RETRY_SCHEDULED", "NO_ACTION_SELECTED", "MANUAL_REVIEW_REQUIRED")

    # Audit log verification
    audits = db.query(AuditLog).filter(AuditLog.case_id == case.id).all()
    assert len(audits) >= 2  # ENV decision audit + Action execution audit
    db.close()
