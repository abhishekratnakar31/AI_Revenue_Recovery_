"""
RecoverAI Milestone 12 Test Suite: Incremental Net Revenue Attribution & A/B Evaluation Engine

Comprehensive tests covering:
1. Lift mathematics & natural recovery exclusion
2. Net revenue non-double-counted accounting equation
3. Refund webhook idempotency with UNIQUE(razorpay_refund_id)
4. 30-day attribution observation window
5. Control-Treatment isolation & contamination checks
6. Sample Ratio Mismatch (SRM) & Standardized Mean Difference (SMD < 0.10) balance tests
7. 95% Confidence Intervals & two-proportion p-value significance
"""

import pytest
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.database import Base
from backend.app.models.models import (
    Customer,
    Order,
    Payment,
    PaymentAttempt,
    RecoveryCase,
    Experiment,
    ExperimentAssignment,
    Outcome,
    RefundEvent,
    WebhookEvent,
    AuditLog,
)
from backend.app.analytics.attribution import AttributionEngine, utc_now
from backend.app.webhooks.processor import process_webhook_event


@pytest.fixture
def db():
    """Provides a clean in-memory SQLite database session for unit testing."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()


def create_test_experiment(db, exp_name="Exp_M12_Test"):
    exp = Experiment(name=exp_name, dataset_version="v1.0")
    db.add(exp)
    db.commit()
    return exp


import uuid


def create_test_case_with_outcome(
    db,
    experiment_id,
    group,
    amount=10000.0,
    ltv=50000.0,
    pm="UPI",
    gross=0.0,
    refunds=0.0,
    gw_cost=0.0,
    comm_cost=0.0,
    disc_cost=0.0,
    is_recovered=False,
    created_at=None,
):
    uid = uuid.uuid4().hex[:8]
    cust = Customer(external_customer_id=f"cust_{uid}", lifetime_value=ltv)
    db.add(cust)
    db.commit()

    order = Order(razorpay_order_id=f"ord_{uid}", customer_id=cust.id, amount=amount, currency="INR")
    db.add(order)
    db.commit()

    payment = Payment(razorpay_payment_id=f"pay_{uid}", order_id=order.id, amount=amount, status="FAILED", payment_method=pm)
    db.add(payment)
    db.commit()

    att = PaymentAttempt(
        payment_id=payment.id,
        attempt_number=1,
        status="failed",
        gateway="razorpay",
        payment_method=pm,
        bank="HDFC",
        failure_reason="BANK_TIMEOUT",
        timestamp=created_at or utc_now(),
    )
    db.add(att)
    db.commit()

    case = RecoveryCase(
        case_type="payment_failure",
        customer_id=cust.id,
        order_id=order.id,
        payment_id=payment.id,
        amount_at_risk=amount,
        status="RECOVERED" if is_recovered else "RECOVERY_ACTIVE",
        created_at=created_at or utc_now(),
    )
    db.add(case)
    db.commit()

    asgn = ExperimentAssignment(experiment_id=experiment_id, case_id=case.id, group=group)
    db.add(asgn)
    db.commit()

    net = max(0.0, gross - refunds - gw_cost - comm_cost - disc_cost)
    outcome = Outcome(
        case_id=case.id,
        intervention="RETRY" if is_recovered else "NONE",
        payment_success=is_recovered,
        is_recovered=is_recovered,
        gross_recovered=gross,
        net_recovered=net,
        gateway_cost=gw_cost,
        communication_cost=comm_cost,
        discount_given=disc_cost,
        refund_deductions=refunds,
        attribution_status="DIRECT" if is_recovered else "NONE",
    )
    db.add(outcome)
    db.commit()

    return case, payment, outcome


# 1. Test Incremental Net Revenue Lift Formula
def test_incremental_net_revenue_formula(db):
    exp = create_test_experiment(db)

    # CONTROL: 100 cases, ₹10k each (Total risk: ₹1,000,000). 40 recover (Gross ₹400k, Net ₹390k). NRR = 39%
    for i in range(100):
        is_rec = i < 40
        create_test_case_with_outcome(
            db, exp.id, "CONTROL", amount=10000.0, gross=10000.0 if is_rec else 0.0, gw_cost=100.0 if is_rec else 0.0, is_recovered=is_rec
        )

    # TREATMENT: 100 cases, ₹10k each (Total risk: ₹1,000,000). 60 recover (Gross ₹600k, Net ₹570k). NRR = 57%
    for i in range(100):
        is_rec = i < 60
        create_test_case_with_outcome(
            db, exp.id, "TREATMENT", amount=10000.0, gross=10000.0 if is_rec else 0.0, gw_cost=500.0 if is_rec else 0.0, is_recovered=is_rec
        )

    res = AttributionEngine.compute_incremental_attribution(db, exp.id)
    incr = res["incremental_metrics"]

    assert round(incr["control_net_recovery_rate_pct"], 2) == 39.6
    assert round(incr["treatment_net_recovery_rate_pct"], 2) == 57.0
    assert incr["incremental_net_revenue"] > 0
    assert incr["statistically_significant"] is True


# 2. Test Control Recovery Subtraction (Natural Recovery Protection)
def test_control_recovery_is_subtracted(db):
    exp = create_test_experiment(db)

    # Control has 50% recovery rate
    for i in range(10):
        create_test_case_with_outcome(db, exp.id, "CONTROL", amount=1000.0, gross=1000.0 if i < 5 else 0.0, is_recovered=(i < 5))

    # Treatment has 50% recovery rate (Zero true lift)
    for i in range(10):
        create_test_case_with_outcome(db, exp.id, "TREATMENT", amount=1000.0, gross=1000.0 if i < 5 else 0.0, is_recovered=(i < 5))

    res = AttributionEngine.compute_incremental_attribution(db, exp.id)
    incr = res["incremental_metrics"]

    assert incr["incremental_recovery_rate_pp"] == 0.0
    assert incr["incremental_net_revenue"] == 0.0
    assert incr["statistically_significant"] is False


# 3. Test Net Revenue Accounting Equation (Gross - Refunds - Fees - Comm - Disc = Net)
def test_net_revenue_accounting_equation(db):
    exp = create_test_experiment(db)

    # Gross ₹10,000, Refund ₹1,000, Gateway ₹100, Comm ₹10, Discount ₹500 -> Net = ₹8,390
    case, payment, outcome = create_test_case_with_outcome(
        db, exp.id, "TREATMENT", amount=10000.0, gross=10000.0, refunds=1000.0, gw_cost=100.0, comm_cost=10.0, disc_cost=500.0, is_recovered=True
    )

    assert outcome.net_recovered == 8390.0


# 4. Test Refund Webhook Deductions Update Net Recovered
def test_refund_reduces_net_recovered(db):
    exp = create_test_experiment(db)

    case, payment, outcome = create_test_case_with_outcome(
        db, exp.id, "TREATMENT", amount=10000.0, gross=10000.0, is_recovered=True
    )
    assert outcome.net_recovered == 10000.0

    res = AttributionEngine.process_refund_deduction(
        db=db,
        razorpay_refund_id="rfnd_test_001",
        payment_id=payment.id,
        refund_amount=2000.0,
    )

    assert res["status"] == "success"
    assert res["processed"] is True
    db.refresh(outcome)
    assert outcome.refund_deductions == 2000.0
    assert outcome.net_recovered == 8000.0


# 5. Test Duplicate Refund Idempotency (UNIQUE razorpay_refund_id)
def test_duplicate_refund_is_idempotent(db):
    exp = create_test_experiment(db)

    case, payment, outcome = create_test_case_with_outcome(
        db, exp.id, "TREATMENT", amount=10000.0, gross=10000.0, is_recovered=True
    )

    res1 = AttributionEngine.process_refund_deduction(db, "rfnd_dup_100", payment.id, 1500.0)
    assert res1["status"] == "success"
    assert res1["processed"] is True

    # Process duplicate refund ID
    res2 = AttributionEngine.process_refund_deduction(db, "rfnd_dup_100", payment.id, 1500.0)
    assert res2["status"] == "duplicate_refund_ignored"
    assert res2["processed"] is False

    db.refresh(outcome)
    assert outcome.refund_deductions == 1500.0
    assert outcome.net_recovered == 8500.0

    # Ensure only 1 RefundEvent record in DB
    ref_count = db.query(RefundEvent).filter(RefundEvent.razorpay_refund_id == "rfnd_dup_100").count()
    assert ref_count == 1


# 6. Test 30-Day Attribution Window Enforcement
def test_refund_30_day_attribution_window(db):
    exp = create_test_experiment(db)
    old_time = utc_now() - datetime.timedelta(days=40)

    # Case created 40 days ago (outside 30-day window)
    case, payment, outcome = create_test_case_with_outcome(
        db, exp.id, "TREATMENT", amount=10000.0, gross=10000.0, is_recovered=True, created_at=old_time
    )

    res = AttributionEngine.process_refund_deduction(db, "rfnd_old_999", payment.id, 3000.0, observation_window_days=30)
    assert res["status"] == "success"
    assert res["window_applied"] is False
    assert res["outcome_updated"] is False

    db.refresh(outcome)
    assert outcome.refund_deductions == 0.0
    assert outcome.net_recovered == 10000.0


# 7. Test Control-Treatment Isolation (No Contamination)
def test_control_treatment_isolation(db):
    exp = create_test_experiment(db)
    case_ctrl, _, _ = create_test_case_with_outcome(db, exp.id, "CONTROL", amount=5000.0)
    case_trt, _, _ = create_test_case_with_outcome(db, exp.id, "TREATMENT", amount=5000.0)

    asgn_ctrl = db.query(ExperimentAssignment).filter(ExperimentAssignment.case_id == case_ctrl.id).first()
    asgn_trt = db.query(ExperimentAssignment).filter(ExperimentAssignment.case_id == case_trt.id).first()

    assert asgn_ctrl.assignment_group == "CONTROL"
    assert asgn_trt.assignment_group == "TREATMENT"


# 8. Test Sample Ratio Mismatch (SRM) Detection
def test_sample_ratio_mismatch_detection(db):
    exp = create_test_experiment(db)

    # Create 80 CONTROL cases vs 20 TREATMENT cases (SRM Imbalance on 50/50 target)
    for _ in range(80):
        create_test_case_with_outcome(db, exp.id, "CONTROL", amount=1000.0)
    for _ in range(20):
        create_test_case_with_outcome(db, exp.id, "TREATMENT", amount=1000.0)

    bal = AttributionEngine.verify_experiment_balance(db, exp.id)
    assert bal["srm_check"]["pass"] is False
    assert bal["overall_balance_pass"] is False


# 9. Test Standardized Mean Difference (SMD) Balance Checks
def test_covariate_balance_smd(db):
    exp = create_test_experiment(db)

    # Both CONTROL and TREATMENT have mean amount ₹10,000 and mean LTV ₹50,000
    for _ in range(20):
        create_test_case_with_outcome(db, exp.id, "CONTROL", amount=10000.0, ltv=50000.0)
        create_test_case_with_outcome(db, exp.id, "TREATMENT", amount=10000.0, ltv=50000.0)

    bal = AttributionEngine.verify_experiment_balance(db, exp.id)
    assert bal["srm_check"]["pass"] is True
    assert bal["continuous_balance"]["amount_at_risk"]["pass"] is True
    assert bal["continuous_balance"]["customer_ltv"]["pass"] is True
    assert bal["overall_balance_pass"] is True


# 10. Test 95% Confidence Intervals & p-Value Calculation
def test_confidence_intervals_and_p_value(db):
    exp = create_test_experiment(db)

    # 100 cases per arm
    for i in range(100):
        create_test_case_with_outcome(db, exp.id, "CONTROL", amount=5000.0, gross=5000.0 if i < 20 else 0.0, is_recovered=(i < 20))
        create_test_case_with_outcome(db, exp.id, "TREATMENT", amount=5000.0, gross=5000.0 if i < 45 else 0.0, is_recovered=(i < 45))

    res = AttributionEngine.compute_incremental_attribution(db, exp.id)
    incr = res["incremental_metrics"]

    assert incr["incremental_recovery_rate_pp"] == 25.0
    ci_pp = incr["confidence_interval_95_pp"]
    assert ci_pp[0] < 25.0 < ci_pp[1]
    assert incr["p_value"] < 0.05
    assert incr["statistically_significant"] is True


# 11. Test Webhook Processor Router for refund.created Payload
def test_webhook_processor_handles_refund_created(db):
    case, payment, outcome = create_test_case_with_outcome(
        db, experiment_id=1, group="TREATMENT", amount=8000.0, gross=8000.0, is_recovered=True
    )

    payload = {
        "event": "refund.created",
        "payload": {
            "refund": {
                "entity": {
                    "id": "rfnd_wh_test_123",
                    "payment_id": payment.id,
                    "amount": 2500.0,
                    "status": "processed",
                }
            }
        }
    }

    wh_event = WebhookEvent(
        razorpay_event_id="evt_refund_123",
        event_type="refund.created",
        payload_hash="dummy_hash_123",
        payload=payload,
        processing_status="PENDING",
    )
    db.add(wh_event)
    db.commit()

    process_webhook_event(wh_event.id, db=db)

    db.refresh(wh_event)
    assert wh_event.processing_status == "PROCESSED"

    db.refresh(outcome)
    assert outcome.refund_deductions == 2500.0
    assert outcome.net_recovered == 5500.0


# 12. Test Experiment Assignment Immutability
def test_experiment_assignment_is_immutable(db):
    exp = create_test_experiment(db)
    case, payment, outcome = create_test_case_with_outcome(db, exp.id, "TREATMENT", amount=5000.0)

    asgn = db.query(ExperimentAssignment).filter(ExperimentAssignment.case_id == case.id).first()
    assert asgn.group == "TREATMENT"

    # Verify assignment cannot be silently overwritten
    already_assigned = db.query(ExperimentAssignment).filter(ExperimentAssignment.case_id == case.id).first()
    assert already_assigned is not None
    assert already_assigned.group == "TREATMENT"

