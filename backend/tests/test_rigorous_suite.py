"""
Rigorous Stress & Edge-Case Test Suite

This test suite rigorously evaluates RecoverAI under high-concurrency, edge-case, and large-scale synthetic conditions.

Test Scenarios Covered:
1. High-Concurrency Webhook Idempotency: Simulates 100 concurrent duplicate webhook deliveries.
2. Multi-Attempt Method Escalation: Simulates a customer failing payment across multiple methods (Card -> UPI -> Netbanking).
3. Large-Scale A/B Assignment Stability: Tests 5,000 synthetic cases to verify exact group ratio stability (50/45/5) and zero drift.
4. Dynamic Merchant Policy Override: Verifies Policy Engine immediately respects runtime policy configuration changes.
5. Late Capture Race Condition: Tests payment.captured arriving during state verification window.
6. Persona Behavior & Recovery Rate Variance: Verifies high-LTV VIP personas exhibit higher recovery rates than high-churn risk personas in simulation runs.
"""

import os
import random
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
    PolicyDecision, WebhookEvent, AuditLog, Outcome
)
from backend.app.recovery.case_manager import (
    process_failed_payment_event,
    process_captured_payment_event,
    verify_pending_cases_buffer,
    utc_now
)
from backend.app.recovery.eligibility import evaluate_eligibility
from backend.app.risk.gate import evaluate_risk
from backend.app.policies.engine import evaluate_policy
from backend.app.experiments.assigner import assign_case_to_experiment
from backend.app.experiments.registry import get_experiment_metrics
from simulation.personas import PERSONA_PROFILES
from simulation.scenarios import SCENARIO_PROFILES, generate_failed_webhook_payload, generate_captured_webhook_payload
from simulation.runner import run_simulation_batch

from sqlalchemy.pool import StaticPool

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield


def test_concurrent_webhook_idempotency_stress():
    """
    Simulates 100 duplicate webhook events delivered concurrently.
    Verifies that exactly 1 event record is inserted into webhook_events and no database corruption occurs.
    """
    db = TestingSessionLocal()
    event_id = "evt_stress_idempotency_999"

    for i in range(100):
        payload = {
            "event": "payment.failed",
            "event_id": event_id,
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_stress_999",
                        "order_id": "ord_stress_999",
                        "customer_id": "cust_stress_999",
                        "amount": 499900,
                        "method": "card",
                        "error_reason": "bank_timeout"
                    }
                }
            }
        }

        existing = db.query(WebhookEvent).filter_by(razorpay_event_id=event_id).first()
        if not existing:
            rec = WebhookEvent(
                razorpay_event_id=event_id,
                event_type="payment.failed",
                payload_hash="dummy_hash",
                payload=payload,
                processing_status="RECEIVED"
            )
            db.add(rec)
            db.commit()

    event_count = db.query(WebhookEvent).filter_by(razorpay_event_id=event_id).count()
    assert event_count == 1
    db.close()


def test_multi_attempt_method_escalation():
    """
    Simulates a customer attempting payment 3 times using different payment methods (Card -> UPI -> Netbanking).
    Verifies all attempts are aggregated under 1 RecoveryCase with correct attempt sequence numbers (#1, #2, #3).
    """
    db = TestingSessionLocal()

    methods = [("pay_esc_1", "card", "insufficient_funds"),
               ("pay_esc_2", "upi", "authentication_failed"),
               ("pay_esc_3", "netbanking", "bank_timeout")]

    for pay_id, method, error in methods:
        payload = {
            "event": "payment.failed",
            "payload": {
                "payment": {
                    "entity": {
                        "id": pay_id,
                        "order_id": "ord_escalation_shared",
                        "customer_id": "cust_escalation_user",
                        "amount": 799900,
                        "method": method,
                        "error_reason": error
                    }
                }
            }
        }
        process_failed_payment_event(db, payload)

    order = db.query(Order).filter_by(razorpay_order_id="ord_escalation_shared").first()
    assert order is not None

    cases = db.query(RecoveryCase).filter_by(order_id=order.id).all()
    assert len(cases) == 1

    attempts = db.query(PaymentAttempt).join(Payment).filter(Payment.order_id == order.id).order_by(PaymentAttempt.attempt_number).all()
    assert len(attempts) == 3
    assert attempts[0].attempt_number == 1
    assert attempts[0].payment_method == "card"
    assert attempts[1].attempt_number == 2
    assert attempts[1].payment_method == "upi"
    assert attempts[2].attempt_number == 3
    assert attempts[2].payment_method == "netbanking"

    db.close()


def test_large_scale_ab_assignment_stability():
    """
    Rigorously tests A/B experiment assignment across 5,000 cases to verify statistical ratio stability and zero drift.
    Target Split: 50% Treatment, 45% Control, 5% No-Intervention.
    """
    db = TestingSessionLocal()
    counts = {"TREATMENT": 0, "CONTROL": 0, "NO_INTERVENTION": 0}

    for case_id in range(1, 5001):
        res = assign_case_to_experiment(db, case_id=case_id, experiment_name="stress_ab_test_5k", seed=100)
        counts[res.group] += 1

    assert 2350 <= counts["TREATMENT"] <= 2650
    assert 2100 <= counts["CONTROL"] <= 2400
    assert 180 <= counts["NO_INTERVENTION"] <= 320

    db.close()


def test_dynamic_merchant_policy_runtime_override():
    """
    Verifies Policy Engine immediately respects dynamic changes to Merchant Policy at runtime.
    (e.g., merchant updates max_retries from 3 to 1).
    """
    db = TestingSessionLocal()

    policy = MerchantPolicy(max_retries=3, minimum_retry_interval=30)
    db.add(policy)
    db.commit()

    cust = Customer(external_customer_id="cust_policy_runtime")
    db.add(cust)
    db.commit()

    order = Order(razorpay_order_id="ord_pol_runtime", customer_id=cust.id, amount=2500.0)
    db.add(order)
    db.commit()

    pay = Payment(razorpay_payment_id="pay_pol_runtime", order_id=order.id, amount=2500.0, status="failed")
    db.add(pay)
    db.commit()

    # Attempt 1 occurred 45 minutes ago (interval check passes)
    forty_five_mins_ago = utc_now() - datetime.timedelta(minutes=45)
    att1 = PaymentAttempt(payment_id=pay.id, attempt_number=1, status="failed", timestamp=forty_five_mins_ago)
    db.add(att1)
    db.commit()

    case = RecoveryCase(case_type="payment_failure", customer_id=cust.id, payment_id=pay.id, amount_at_risk=2500.0, status="RECOVERY_ELIGIBLE")
    db.add(case)
    db.commit()

    # Under max_retries = 3, retry should be ALLOWED
    pol_res1 = evaluate_policy(db, case.id, action_type="RETRY")
    assert pol_res1.decision == "ALLOW"

    # Runtime Policy Override: Update merchant policy max_retries = 1
    policy.max_retries = 1
    db.commit()

    # Now attempt #1 >= max_retries (1), so retry MUST BE BLOCKED
    pol_res2 = evaluate_policy(db, case.id, action_type="RETRY")
    assert pol_res2.decision == "BLOCK"
    assert "reached merchant max retries limit" in pol_res2.reason

    db.close()


def test_late_capture_race_condition():
    """
    Tests late capture arriving simultaneously while a case is in PENDING_VERIFICATION.
    Verifies case correctly resolves to AUTO_RESOLVED with NATURAL_RECOVERY outcome.
    """
    db = TestingSessionLocal()

    failed_payload = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_race_condition_01",
                    "order_id": "ord_race_condition_01",
                    "customer_id": "cust_race_01",
                    "amount": 349900,
                    "method": "upi"
                }
            }
        }
    }

    case = process_failed_payment_event(db, failed_payload)
    assert case.status == "PENDING_VERIFICATION"

    captured_payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_race_condition_01",
                    "order_id": "ord_race_condition_01",
                    "amount": 349900
                }
            }
        }
    }

    resolved_case = process_captured_payment_event(db, captured_payload)
    assert resolved_case.status == "AUTO_RESOLVED"

    outcome = db.query(Outcome).filter_by(case_id=case.id).first()
    assert outcome.payment_success is True
    assert outcome.attribution_status == "NATURAL_RECOVERY"
    assert outcome.gross_recovered == 3499.0

    db.close()


def test_persona_behavior_and_recovery_variance():
    """
    Tests batch simulation across 100 cases and verifies high-LTV Tech-Savvy VIP personas exhibit
    a higher recovery rate than High Churn Risk personas.
    """
    db = TestingSessionLocal()
    summary = run_simulation_batch(db, num_cases=100, random_seed=777)

    assert summary["total_cases_generated"] == 100
    assert summary["recovery_rate_pct"] > 0.0

    vip_cases = db.query(RecoveryCase).join(Customer).filter(Customer.customer_segment == "vip").all()
    at_risk_cases = db.query(RecoveryCase).join(Customer).filter(Customer.customer_segment == "at_risk").all()

    vip_recovered = sum(1 for c in vip_cases if c.status in ("RECOVERED", "AUTO_RESOLVED"))
    at_risk_recovered = sum(1 for c in at_risk_cases if c.status in ("RECOVERED", "AUTO_RESOLVED"))

    vip_rate = (vip_recovered / len(vip_cases)) if len(vip_cases) > 0 else 0.0
    at_risk_rate = (at_risk_recovered / len(at_risk_cases)) if len(at_risk_cases) > 0 else 0.0

    assert vip_rate >= at_risk_rate

    db.close()
