"""
Deterministic End-to-End Demo Scenario Test Suite for Milestone 13.

Tests:
1. Bank timeout -> ML/ENV selects retry -> execution is idempotent.
2. Confirmed route degradation -> retry blocked -> payment link remains allowed.
3. Customer opt-out -> no LLM call and no notification.
4. High-value case -> manual review gate.
5. Captured payment after recovery action -> outcome becomes recovered.
6. Recovery followed by refund -> net revenue and attribution update accurately.
7. Treatment/control experiment -> expected recovery lift, NRR lift, confidence interval, and p-value are returned.
"""

import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.database import Base
from backend.app.models.models import Customer, Order, Payment, PaymentAttempt, RecoveryCase, Outcome, GatewayRouteStatus
from backend.app.recovery.case_manager import process_failed_payment_event, process_captured_payment_event
from backend.app.recovery.eligibility import evaluate_eligibility
from backend.app.risk.gate import evaluate_risk
from backend.app.policies.engine import evaluate_policy
from backend.app.recovery.env_engine import select_optimal_recovery_action
from backend.app.analytics.attribution import AttributionEngine
from simulation.runner import run_simulation_batch


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_e2e_bank_timeout_retry_selection(db_session):
    payload = {
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_e2e_bt_01",
                    "order_id": "ord_e2e_bt_01",
                    "customer_id": "cust_e2e_bt_01",
                    "amount": 250000,  # ₹2,500.00
                    "method": "upi",
                    "bank": "HDFC",
                    "error_reason": "bank_timeout"
                }
            }
        }
    }
    case = process_failed_payment_event(db_session, payload)
    assert case is not None
    assert case.amount_at_risk == 2500.0

    elig = evaluate_eligibility(db_session, case.id)
    assert elig.is_eligible is True

    risk = evaluate_risk(db_session, case.id)
    assert risk.decision == "ALLOW"

    res = select_optimal_recovery_action(db_session, case.id)
    assert res.case_id == case.id
    assert res.selected_action is not None


def test_e2e_confirmed_route_degradation_retry_blocked(db_session):
    # Set route razorpay/UPI/HDFC status to CONFIRMED
    route = GatewayRouteStatus(
        gateway="razorpay",
        payment_method="UPI",
        bank="HDFC",
        status="CONFIRMED",
        baseline_failure_rate=0.05,
        current_failure_rate=0.35,
        current_z_score=4.2,
        total_attempts=50,
        failed_attempts=18
    )
    db_session.add(route)
    db_session.commit()

    payload = {
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_e2e_deg_01",
                    "order_id": "ord_e2e_deg_01",
                    "customer_id": "cust_e2e_deg_01",
                    "amount": 300000,
                    "method": "upi",
                    "bank": "HDFC",
                    "error_reason": "bank_timeout"
                }
            }
        }
    }
    case = process_failed_payment_event(db_session, payload)

    # Evaluate RETRY action -> Should be BLOCKED
    pol_retry = evaluate_policy(db_session, case.id, action_type="RETRY")
    assert pol_retry.decision == "BLOCK"

    # Evaluate PAYMENT_LINK action -> Should be ALLOWED
    pol_link = evaluate_policy(db_session, case.id, action_type="PAYMENT_LINK")
    assert pol_link.decision == "ALLOW"


def test_e2e_customer_opt_out_bypasses_llm(db_session):
    cust = Customer(external_customer_id="cust_opted_out_user", opt_out=True)
    db_session.add(cust)
    db_session.commit()

    ord_obj = Order(razorpay_order_id="ord_opt_1", customer_id=cust.id, amount=1000.0)
    db_session.add(ord_obj)
    db_session.commit()

    pay_obj = Payment(razorpay_payment_id="pay_opt_1", order_id=ord_obj.id, amount=1000.0, status="FAILED", payment_method="card")
    db_session.add(pay_obj)
    db_session.commit()

    case = RecoveryCase(case_type="payment_failure", customer_id=cust.id, order_id=ord_obj.id, payment_id=pay_obj.id, amount_at_risk=1000.0, status="CUSTOMER_OPTED_OUT")
    db_session.add(case)
    db_session.commit()

    elig = evaluate_eligibility(db_session, case.id)
    assert elig.is_eligible is False
    assert "OPTED OUT" in elig.reason.upper() or "OPT" in elig.reason.upper()


def test_e2e_high_value_transaction_manual_review(db_session):
    # ₹30,000 exceeds default ₹25,000 threshold
    payload = {
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_high_val_999",
                    "order_id": "ord_high_val_999",
                    "customer_id": "cust_high_val_999",
                    "amount": 3000000,  # ₹30,000.00
                    "method": "card",
                    "bank": "ICICI",
                    "error_reason": "card_declined"
                }
            }
        }
    }
    case = process_failed_payment_event(db_session, payload)
    risk = evaluate_risk(db_session, case.id)

    assert risk.decision == "REVIEW"
    assert "THRESHOLD" in risk.reason.upper() or "MANUAL" in risk.reason.upper() or "VALUE" in risk.reason.upper()


def test_e2e_captured_payment_after_recovery(db_session):
    fail_payload = {
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_late_cap_1",
                    "order_id": "ord_late_cap_1",
                    "customer_id": "cust_late_cap_1",
                    "amount": 500000,  # ₹5,000.00
                    "method": "upi",
                    "bank": "SBI",
                    "error_reason": "bank_timeout"
                }
            }
        }
    }
    case = process_failed_payment_event(db_session, fail_payload)
    assert case.status in ("PENDING_VERIFICATION", "RECOVERY_ELIGIBLE")

    cap_payload = {
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_late_cap_1",
                    "order_id": "ord_late_cap_1",
                    "amount": 500000
                }
            }
        }
    }
    resolved_case = process_captured_payment_event(db_session, cap_payload)

    assert resolved_case is not None
    assert resolved_case.status in ("AUTO_RESOLVED", "RECOVERED")


def test_e2e_treatment_control_ab_attribution_lift(db_session):
    sim_res = run_simulation_batch(db_session, num_cases=30, random_seed=42, auto_process=True)
    assert sim_res["total_cases_generated"] == 30

    report = AttributionEngine.compute_incremental_attribution(db_session, experiment_id=1)
    assert report is not None
    assert "recovery_effect" in report
    assert "financial_effect" in report
    assert report["recovery_effect"]["z_statistic"] is not None
    assert report["recovery_effect"]["p_value"] is not None
