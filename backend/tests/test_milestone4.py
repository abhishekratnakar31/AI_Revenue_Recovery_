"""
Milestone 4 Test Suite

Tests:
1. Eligibility Filter Engine (Customer opt-out, case expiration, permanent failure, max retries limit, standard pass).
2. Risk Gate (Fraud flags, high-value transaction manual review threshold, standard pass).
3. Deterministic Policy Engine (Max retries rule, minimum retry interval rule, customer fatigue limit rule, discount cap rule, policy decisions DB persistence).
"""

import os
import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Set test environment
os.environ["USE_TEST_DB"] = "1"
os.environ["TEST_DATABASE_URL"] = "sqlite:///./test.db"

from backend.app.core.database import Base
from backend.app.models.models import (
    Customer, Order, Payment, PaymentAttempt, RecoveryCase, MerchantPolicy,
    PolicyDecision, NotificationEvent, AuditLog
)
from backend.app.recovery.eligibility import evaluate_eligibility, utc_now
from backend.app.risk.gate import evaluate_risk
from backend.app.policies.engine import evaluate_policy

engine = create_engine("sqlite:///./test.db", connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def test_eligibility_customer_opt_out():
    db = TestingSessionLocal()
    cust = Customer(external_customer_id="cust_opted_out", opt_out=True)
    db.add(cust)
    db.commit()

    case = RecoveryCase(case_type="payment_failure", customer_id=cust.id, amount_at_risk=4999.0, status="PENDING_VERIFICATION")
    db.add(case)
    db.commit()

    res = evaluate_eligibility(db, case.id)
    assert res.is_eligible is False
    assert res.status == "CUSTOMER_OPTED_OUT"

    db.refresh(case)
    assert case.status == "CUSTOMER_OPTED_OUT"
    assert case.closed_at is not None
    db.close()


def test_eligibility_permanent_failure():
    db = TestingSessionLocal()
    cust = Customer(external_customer_id="cust_perm_fail")
    db.add(cust)
    db.commit()

    order = Order(razorpay_order_id="ord_perm", customer_id=cust.id, amount=2000.0)
    db.add(order)
    db.commit()

    pay = Payment(razorpay_payment_id="pay_perm", order_id=order.id, amount=2000.0, status="failed")
    db.add(pay)
    db.commit()

    attempt = PaymentAttempt(payment_id=pay.id, attempt_number=1, status="failed", failure_reason="card_stolen")
    db.add(attempt)
    db.commit()

    case = RecoveryCase(case_type="payment_failure", customer_id=cust.id, payment_id=pay.id, amount_at_risk=2000.0, status="PENDING_VERIFICATION")
    db.add(case)
    db.commit()

    res = evaluate_eligibility(db, case.id)
    assert res.is_eligible is False
    assert res.status == "FAILED_PERMANENTLY"
    db.close()


def test_eligibility_case_expired():
    db = TestingSessionLocal()
    past_time = utc_now() - datetime.timedelta(hours=80)
    cust = Customer(external_customer_id="cust_expired")
    db.add(cust)
    db.commit()

    case = RecoveryCase(case_type="payment_failure", customer_id=cust.id, amount_at_risk=1000.0, status="PENDING_VERIFICATION", attribution_window=72, created_at=past_time)
    db.add(case)
    db.commit()

    res = evaluate_eligibility(db, case.id)
    assert res.is_eligible is False
    assert res.status == "EXPIRED"
    db.close()


def test_eligibility_max_retries_reached():
    db = TestingSessionLocal()
    policy = MerchantPolicy(max_retries=2)
    db.add(policy)
    db.commit()

    cust = Customer(external_customer_id="cust_max_retries")
    db.add(cust)
    db.commit()

    order = Order(razorpay_order_id="ord_max_retries", customer_id=cust.id, amount=3000.0)
    db.add(order)
    db.commit()

    pay = Payment(razorpay_payment_id="pay_max_retries", order_id=order.id, amount=3000.0, status="failed")
    db.add(pay)
    db.commit()

    att1 = PaymentAttempt(payment_id=pay.id, attempt_number=1, status="failed", failure_reason="bank_timeout")
    att2 = PaymentAttempt(payment_id=pay.id, attempt_number=2, status="failed", failure_reason="bank_timeout")
    db.add_all([att1, att2])
    db.commit()

    case = RecoveryCase(case_type="payment_failure", customer_id=cust.id, payment_id=pay.id, amount_at_risk=3000.0, status="PENDING_VERIFICATION")
    db.add(case)
    db.commit()

    res = evaluate_eligibility(db, case.id)
    assert res.is_eligible is False
    assert res.status == "MAX_RETRIES_REACHED"
    db.close()


def test_eligibility_valid_pass():
    db = TestingSessionLocal()
    cust = Customer(external_customer_id="cust_valid_pass")
    db.add(cust)
    db.commit()

    case = RecoveryCase(case_type="payment_failure", customer_id=cust.id, amount_at_risk=5000.0, status="PENDING_VERIFICATION")
    db.add(case)
    db.commit()

    res = evaluate_eligibility(db, case.id)
    assert res.is_eligible is True
    assert res.status == "RECOVERY_ELIGIBLE"

    db.refresh(case)
    assert case.status == "RECOVERY_ELIGIBLE"
    db.close()


def test_risk_gate_fraud_block():
    db = TestingSessionLocal()
    cust = Customer(external_customer_id="cust_fraud")
    db.add(cust)
    db.commit()

    order = Order(razorpay_order_id="ord_fraud", customer_id=cust.id, amount=10000.0)
    db.add(order)
    db.commit()

    pay = Payment(razorpay_payment_id="pay_fraud", order_id=order.id, amount=10000.0, status="failed")
    db.add(pay)
    db.commit()

    attempt = PaymentAttempt(payment_id=pay.id, attempt_number=1, status="failed", failure_reason="fraud_rejection")
    db.add(attempt)
    db.commit()

    case = RecoveryCase(case_type="payment_failure", customer_id=cust.id, payment_id=pay.id, amount_at_risk=10000.0, status="RECOVERY_ELIGIBLE")
    db.add(case)
    db.commit()

    risk_res = evaluate_risk(db, case.id)
    assert risk_res.decision == "BLOCK"
    assert risk_res.risk_score >= 0.9

    db.refresh(case)
    assert case.status == "POLICY_BLOCKED"

    # Verify policy decision database record
    pol_dec = db.query(PolicyDecision).filter_by(recovery_case_id=case.id).first()
    assert pol_dec.decision == "BLOCK"
    db.close()


def test_risk_gate_manual_review_threshold():
    db = TestingSessionLocal()
    policy = MerchantPolicy(manual_approval_threshold=25000.0)
    db.add(policy)
    db.commit()

    cust = Customer(external_customer_id="cust_high_value")
    db.add(cust)
    db.commit()

    case = RecoveryCase(case_type="payment_failure", customer_id=cust.id, amount_at_risk=35000.0, status="RECOVERY_ELIGIBLE")
    db.add(case)
    db.commit()

    risk_res = evaluate_risk(db, case.id)
    assert risk_res.decision == "REVIEW"
    assert "exceeds" in risk_res.reason.lower()

    pol_dec = db.query(PolicyDecision).filter_by(recovery_case_id=case.id).first()
    assert pol_dec.decision == "REVIEW"
    db.close()


def test_risk_gate_allow_normal():
    db = TestingSessionLocal()
    cust = Customer(external_customer_id="cust_normal_risk")
    db.add(cust)
    db.commit()

    case = RecoveryCase(case_type="payment_failure", customer_id=cust.id, amount_at_risk=4999.0, status="RECOVERY_ELIGIBLE")
    db.add(case)
    db.commit()

    risk_res = evaluate_risk(db, case.id)
    assert risk_res.decision == "ALLOW"
    assert risk_res.risk_score == 0.1
    db.close()


def test_policy_engine_customer_fatigue():
    db = TestingSessionLocal()
    policy = MerchantPolicy(max_notifications_per_24h=2)
    db.add(policy)
    db.commit()

    cust = Customer(external_customer_id="cust_fatigued")
    db.add(cust)
    db.commit()

    case = RecoveryCase(case_type="payment_failure", customer_id=cust.id, amount_at_risk=3000.0, status="RECOVERY_ELIGIBLE")
    db.add(case)
    db.commit()

    # Add 2 notification events in past 24 hours
    n1 = NotificationEvent(customer_id=cust.id, recovery_case_id=case.id, channel="email", notification_type="payment_link")
    n2 = NotificationEvent(customer_id=cust.id, recovery_case_id=case.id, channel="sms", notification_type="reminder")
    db.add_all([n1, n2])
    db.commit()

    # Evaluate notification action
    pol_res = evaluate_policy(db, case.id, action_type="PAYMENT_LINK")
    assert pol_res.decision == "BLOCK"
    assert "received 2 notifications" in pol_res.reason

    pol_dec = db.query(PolicyDecision).filter_by(recovery_case_id=case.id, action_type="PAYMENT_LINK").first()
    assert pol_dec.decision == "BLOCK"
    db.close()


def test_policy_engine_retry_interval():
    db = TestingSessionLocal()
    policy = MerchantPolicy(minimum_retry_interval=30)
    db.add(policy)
    db.commit()

    cust = Customer(external_customer_id="cust_recent_retry")
    db.add(cust)
    db.commit()

    order = Order(razorpay_order_id="ord_recent_retry", customer_id=cust.id, amount=2000.0)
    db.add(order)
    db.commit()

    pay = Payment(razorpay_payment_id="pay_recent_retry", order_id=order.id, amount=2000.0, status="failed")
    db.add(pay)
    db.commit()

    # Last attempt 10 minutes ago
    ten_mins_ago = utc_now() - datetime.timedelta(minutes=10)
    att = PaymentAttempt(payment_id=pay.id, attempt_number=1, status="failed", timestamp=ten_mins_ago)
    db.add(att)
    db.commit()

    case = RecoveryCase(case_type="payment_failure", customer_id=cust.id, payment_id=pay.id, amount_at_risk=2000.0, status="RECOVERY_ELIGIBLE")
    db.add(case)
    db.commit()

    # Trigger immediate retry policy check
    pol_res = evaluate_policy(db, case.id, action_type="RETRY")
    assert pol_res.decision == "BLOCK"
    assert "minutes elapsed since last attempt" in pol_res.reason
    db.close()


def test_policy_engine_discount_cap():
    db = TestingSessionLocal()
    policy = MerchantPolicy(max_discount_percentage=10.0)
    db.add(policy)
    db.commit()

    cust = Customer(external_customer_id="cust_discount")
    db.add(cust)
    db.commit()

    case = RecoveryCase(case_type="payment_failure", customer_id=cust.id, amount_at_risk=5000.0, status="RECOVERY_ELIGIBLE")
    db.add(case)
    db.commit()

    # Proposed discount of 15% should be BLOCKED
    pol_res = evaluate_policy(db, case.id, action_type="PAYMENT_LINK", proposed_discount=15.0)
    assert pol_res.decision == "BLOCK"
    assert "exceeds merchant cap" in pol_res.reason
    db.close()


def test_policy_engine_valid_allow():
    db = TestingSessionLocal()
    cust = Customer(external_customer_id="cust_policy_allow")
    db.add(cust)
    db.commit()

    case = RecoveryCase(case_type="payment_failure", customer_id=cust.id, amount_at_risk=4999.0, status="RECOVERY_ELIGIBLE")
    db.add(case)
    db.commit()

    pol_res = evaluate_policy(db, case.id, action_type="PAYMENT_LINK")
    assert pol_res.decision == "ALLOW"
    assert "approved under merchant policy" in pol_res.reason

    pol_dec = db.query(PolicyDecision).filter_by(recovery_case_id=case.id, action_type="PAYMENT_LINK").first()
    assert pol_dec.decision == "ALLOW"
    db.close()
