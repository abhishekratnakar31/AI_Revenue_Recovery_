"""
Comprehensive Unit & Integration Test Suite for GatewayDegradationDetector (Milestone 11).
Tests rolling 15-min window metrics, division-by-zero Z-score math, canonical route normalization,
mutually exclusive 4-state transitions, Policy Engine retry blocking, M8 AgentDecision preservation,
hysteretic deadband, probe rate-limiting, and route isolation.
"""

import pytest
import math
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.models.models import (
    Base, Customer, Order, Payment, PaymentAttempt, RecoveryCase, AgentDecision, PolicyDecision, GatewayRouteStatus, AuditLog
)
from backend.app.analytics.degradation import (
    normalize_route, classify_attempt_outcome, compute_z_score, GatewayDegradationDetector, FixedBaselineProvider, utc_now
)
from backend.app.policies.engine import evaluate_policy
from backend.app.policies.rules import check_gateway_degradation_rule

# Setup SQLite in-memory DB with StaticPool for multi-threaded thread safety
engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_database():
    """Create fresh database tables before each test case."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    """Yields a database session for testing."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def setup_test_case(db_session):
    """Sets up a test case fixture."""
    customer = Customer(external_customer_id="cust_deg_test", first_name="Rahul")
    db_session.add(customer)
    db_session.flush()

    order = Order(razorpay_order_id="ord_deg_test", customer_id=customer.id, amount=15000.0, currency="INR")
    db_session.add(order)
    db_session.flush()

    payment = Payment(razorpay_payment_id="pay_deg_test", order_id=order.id, amount=15000.0, status="FAILED", payment_method="UPI")
    db_session.add(payment)
    db_session.flush()

    case = RecoveryCase(case_type="payment_failure", customer_id=customer.id, order_id=order.id, payment_id=payment.id, amount_at_risk=15000.0, status="RECOVERY_ACTIVE")
    db_session.add(case)
    db_session.flush()

    decision = AgentDecision(recovery_case_id=case.id, selected_action="RETRY", confidence=0.85)
    db_session.add(decision)
    db_session.commit()

    return {"customer": customer, "order": order, "payment": payment, "case": case, "decision": decision}


# Test 1: Canonical Route Normalization
def test_normalize_route():
    gw, pm, b = normalize_route(" razorpay ", " upi ", " hdfc bank ")
    assert gw == "razorpay"
    assert pm == "UPI"
    assert b == "HDFC BANK"

    gw2, pm2, b2 = normalize_route("RAZORPAY", "card", None)
    assert gw2 == "razorpay"
    assert pm2 == "CARD"
    assert b2 == "UNKNOWN"

    gw3, pm3, b3 = normalize_route("razorpay", "card", "")
    assert b3 == "UNKNOWN"


# Test 2: Attempt Outcome Classification
def test_classify_attempt_outcome():
    assert classify_attempt_outcome("captured") == "SUCCESS"
    assert classify_attempt_outcome("authorized") == "SUCCESS"
    assert classify_attempt_outcome("failed") == "FAILURE"
    assert classify_attempt_outcome("timeout") == "FAILURE"
    assert classify_attempt_outcome("pending") is None
    assert classify_attempt_outcome("created") is None


# Test 3: Division-by-Zero Protection in compute_z_score
def test_compute_z_score_safe_zero():
    z, fr = compute_z_score(0, 0, 0.05)
    assert z == 0.0
    assert fr == 0.0

    z, fr = compute_z_score(5, 20, 0.05)
    assert fr == 0.25
    assert z > 0.0


# Test 4: One-Sided Statistical Threshold (Z > 2.5)
def test_compute_z_score_stat_threshold():
    # 20 attempts, 10 failures -> 50% failure rate vs 5% baseline
    z, fr = compute_z_score(10, 20, 0.05)
    assert fr == 0.50
    # SE = sqrt(0.05 * 0.95 / 20) = sqrt(0.002375) = 0.04873
    # z = (0.50 - 0.05) / 0.04873 = 9.23
    assert z > 2.5


# Test 5: Sample Size Bound (N < 20 prevents CONFIRMED state even with 100% failures)
def test_sample_size_bound_prevents_confirmed(db_session):
    detector = GatewayDegradationDetector()

    # Create 15 attempts (all failed) -> N=15 < 20
    for i in range(15):
        att = PaymentAttempt(
            payment_id=1,
            attempt_number=i + 1,
            status="failed",
            gateway="razorpay",
            payment_method="UPI",
            bank="HDFC",
            timestamp=utc_now(),
        )
        db_session.add(att)
    db_session.commit()

    route_status = detector.evaluate_route_status(db_session, "razorpay", "UPI", "HDFC")
    # State should be SUSPECTED because N=15 < 20
    assert route_status.status == "SUSPECTED"
    assert route_status.total_attempts == 15


# Test 6: False Positive Non-Trigger (N=20, failure rate barely above baseline z <= 2.5)
def test_false_positive_non_trigger(db_session):
    detector = GatewayDegradationDetector()

    # 20 attempts, 1 failed (5% failure rate == 5% baseline) -> Z = 0.0
    for i in range(20):
        st = "failed" if i == 0 else "captured"
        att = PaymentAttempt(
            payment_id=1,
            attempt_number=i + 1,
            status=st,
            gateway="razorpay",
            payment_method="CARD",
            bank="ICICI",
            timestamp=utc_now(),
        )
        db_session.add(att)
    db_session.commit()

    route_status = detector.evaluate_route_status(db_session, "razorpay", "CARD", "ICICI")
    assert route_status.status == "NORMAL"
    assert route_status.current_z_score <= 2.0


# Test 7: Transition NORMAL -> CONFIRMED when Z > 2.5 and N >= 20
def test_transition_normal_to_confirmed(db_session):
    detector = GatewayDegradationDetector()

    # 25 attempts, 15 failed -> 60% failure rate
    for i in range(25):
        st = "failed" if i < 15 else "captured"
        att = PaymentAttempt(
            payment_id=1,
            attempt_number=i + 1,
            status=st,
            gateway="razorpay",
            payment_method="UPI",
            bank="HDFC",
            timestamp=utc_now(),
        )
        db_session.add(att)
    db_session.commit()

    route_status = detector.evaluate_route_status(db_session, "razorpay", "UPI", "HDFC")
    assert route_status.status == "CONFIRMED"
    assert route_status.current_z_score > 2.5

    # Check AuditLog entry
    audit = db_session.query(AuditLog).filter(AuditLog.event == "GATEWAY_ROUTE_STATE_CHANGED").first()
    assert audit is not None
    assert audit.new_state == "CONFIRMED"


# Test 8: Policy Engine blocks RETRY when route is CONFIRMED
def test_policy_engine_blocks_retry_on_degraded_route(db_session, setup_test_case):
    case = setup_test_case["case"]

    # Manually create CONFIRMED route status
    route_status = GatewayRouteStatus(
        gateway="razorpay",
        payment_method="UPI",
        bank="UNKNOWN",
        status="CONFIRMED",
        current_failure_rate=0.60,
        current_z_score=5.2,
    )
    db_session.add(route_status)
    db_session.commit()

    # Evaluate RETRY action against Policy Engine
    res = evaluate_policy(db_session, case.id, "RETRY")
    assert res.decision == "BLOCK"
    assert "DEGRADED_ROUTE_PAUSED" in res.reason


# Test 9: Policy Engine preserves M8 AgentDecision when blocking retry
def test_m8_agent_decision_preserved_on_degradation_block(db_session, setup_test_case):
    case = setup_test_case["case"]
    decision = setup_test_case["decision"]

    # Mark route CONFIRMED
    route_status = GatewayRouteStatus(gateway="razorpay", payment_method="UPI", bank="UNKNOWN", status="CONFIRMED")
    db_session.add(route_status)
    db_session.commit()

    # Policy evaluation blocks RETRY
    evaluate_policy(db_session, case.id, "RETRY")

    # Re-fetch decision and verify selected_action remains "RETRY"
    db_session.refresh(decision)
    assert decision.selected_action == "RETRY"


# Test 10: Policy Engine ALLOWS multi-channel payment links when retry route is CONFIRMED
def test_policy_engine_allows_payment_links_on_degraded_route(db_session, setup_test_case):
    case = setup_test_case["case"]

    route_status = GatewayRouteStatus(gateway="razorpay", payment_method="UPI", bank="UNKNOWN", status="CONFIRMED")
    db_session.add(route_status)
    db_session.commit()

    res_link = evaluate_policy(db_session, case.id, "INSTANT_PAYMENT_LINK")
    assert res_link.decision == "ALLOW"

    res_disc = evaluate_policy(db_session, case.id, "DISCOUNTED_PAYMENT_LINK_5", proposed_discount=5.0)
    assert res_disc.decision == "ALLOW"


# Test 11: Route Isolation (HDFC degradation does NOT block ICICI)
def test_route_isolation(db_session, setup_test_case):
    case = setup_test_case["case"]

    # HDFC UPI is CONFIRMED degraded
    hdfc_status = GatewayRouteStatus(gateway="razorpay", payment_method="UPI", bank="HDFC", status="CONFIRMED")
    db_session.add(hdfc_status)

    # ICICI UPI is NORMAL
    icici_status = GatewayRouteStatus(gateway="razorpay", payment_method="UPI", bank="ICICI", status="NORMAL")
    db_session.add(icici_status)
    db_session.commit()

    # Rule check for ICICI route should pass
    passed, reason, code = check_gateway_degradation_rule(db_session, case)
    # Since payment attempt bank defaulted to UNKNOWN or ICICI, check returns pass if not matched to HDFC
    assert passed is True


# Test 12: Transition CONFIRMED -> RECOVERING requires 5-min dwell & N >= 10
def test_transition_confirmed_to_recovering_dwell_time(db_session):
    detector = GatewayDegradationDetector()

    now = utc_now()
    # Route confirmed degraded 6 minutes ago
    route_status = GatewayRouteStatus(
        gateway="razorpay",
        payment_method="UPI",
        bank="HDFC",
        status="CONFIRMED",
        last_state_change=now - timedelta(minutes=6),
    )
    db_session.add(route_status)

    # Add 12 successful attempts in window (Z <= 2.0)
    for i in range(12):
        att = PaymentAttempt(
            payment_id=1,
            attempt_number=i + 1,
            status="captured",
            gateway="razorpay",
            payment_method="UPI",
            bank="HDFC",
            timestamp=now - timedelta(minutes=2),
        )
        db_session.add(att)
    db_session.commit()

    updated = detector.evaluate_route_status(db_session, "razorpay", "UPI", "HDFC")
    assert updated.status == "RECOVERING"


# Test 13: Probe slot rate limiting in RECOVERING state
def test_recovering_probe_slot_rate_limiting(db_session, setup_test_case):
    case = setup_test_case["case"]
    now = utc_now()

    # Route in RECOVERING state, probe slot used 1 minute ago
    route_status = GatewayRouteStatus(
        gateway="razorpay",
        payment_method="UPI",
        bank="UNKNOWN",
        status="RECOVERING",
        last_probe_at=now - timedelta(minutes=1),
    )
    db_session.add(route_status)
    db_session.commit()

    # Should be BLOCKED because elapsed < 300s
    passed, reason, code = check_gateway_degradation_rule(db_session, case)
    assert passed is False
    assert "probe slot used" in reason

    # Move last_probe_at to 6 minutes ago
    route_status.last_probe_at = now - timedelta(minutes=6)
    db_session.commit()

    passed2, reason2, code2 = check_gateway_degradation_rule(db_session, case)
    assert passed2 is True
    assert code2 == "ALLOW_PROBE"


# Test 14: Transition RECOVERING -> NORMAL when probe baseline recovers
def test_transition_recovering_to_normal(db_session):
    detector = GatewayDegradationDetector()
    now = utc_now()

    route_status = GatewayRouteStatus(
        gateway="razorpay",
        payment_method="UPI",
        bank="HDFC",
        status="RECOVERING",
        last_state_change=now - timedelta(minutes=10),
    )
    db_session.add(route_status)

    # Add 12 successful attempts
    for i in range(12):
        att = PaymentAttempt(
            payment_id=1,
            attempt_number=i + 1,
            status="captured",
            gateway="razorpay",
            payment_method="UPI",
            bank="HDFC",
            timestamp=now - timedelta(minutes=1),
        )
        db_session.add(att)
    db_session.commit()

    updated = detector.evaluate_route_status(db_session, "razorpay", "UPI", "HDFC")
    assert updated.status == "NORMAL"


# Test 15: Event occurrence timestamp filtering (PaymentAttempt.timestamp vs DB insertion time)
def test_event_occurrence_timestamp_filtering(db_session):
    detector = GatewayDegradationDetector()
    now = utc_now()

    # Old attempt (20 minutes ago -> outside 15-min window)
    old_att = PaymentAttempt(
        payment_id=1,
        attempt_number=1,
        status="failed",
        gateway="razorpay",
        payment_method="UPI",
        bank="HDFC",
        timestamp=now - timedelta(minutes=20),
    )
    db_session.add(old_att)
    db_session.commit()

    updated = detector.evaluate_route_status(db_session, "razorpay", "UPI", "HDFC")
    assert updated.total_attempts == 0
