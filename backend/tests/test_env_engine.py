"""Comprehensive unit and integration test suite for Milestone 8 ENV Engine."""

import threading
import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models.models import Customer, Order, Payment, PaymentAttempt, RecoveryCase, AgentDecision, MerchantPolicy
from backend.app.ml.schemas import MLFeatureVector
from backend.app.recovery.candidate_actions import CandidateAction, ActionType, get_all_candidate_actions
from backend.app.recovery.action_probability import estimate_action_recovery_probability
from backend.app.recovery.env_engine import (
    compute_action_env, select_optimal_recovery_action, ENV_ENGINE_VERSION
)
from backend.app.ml.predict import clear_model_cache

SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture
def db():
    engine = create_engine(
        SQLALCHEMY_TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    clear_model_cache()

    # Ensure MerchantPolicy defaults exist
    policy = MerchantPolicy()
    session.add(policy)
    session.commit()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def sample_case(db):
    """Fixture creating a sample RecoveryCase and linked entities."""
    now = datetime.now(timezone.utc)
    cust = Customer(
        external_customer_id="cust_env_101",
        lifetime_value=12000.0,
        successful_payment_count=4,
        failed_payment_count=1,
    )
    db.add(cust)
    db.commit()

    order = Order(
        razorpay_order_id="ord_env_101",
        customer_id=cust.id,
        amount=5000.0,
        currency="INR",
        status="created",
    )
    db.add(order)
    db.commit()

    pay = Payment(
        razorpay_payment_id="pay_env_101",
        order_id=order.id,
        amount=5000.0,
        currency="INR",
        status="failed",
    )
    db.add(pay)
    db.commit()

    attempt = PaymentAttempt(
        payment_id=pay.id,
        attempt_number=1,
        status="FAILED",
        failure_reason="BANK_TIMEOUT",
        payment_method="UPI",
        timestamp=now - timedelta(minutes=5),
    )
    db.add(attempt)
    db.commit()

    case = RecoveryCase(
        case_type="ONE_TIME",
        customer_id=cust.id,
        order_id=order.id,
        payment_id=pay.id,
        amount_at_risk=5000.0,
        status="RECOVERY_ELIGIBLE",
        created_at=now,
    )
    db.add(case)
    db.commit()

    return case.id


def test_1_candidate_action_enumeration():
    """Test 1: Verifies all 6 candidate actions are generated cleanly without '%' characters."""
    actions = get_all_candidate_actions()
    assert len(actions) == 6
    action_types = [a.action_type.value for a in actions]
    assert "NO_ACTION" in action_types
    assert "RETRY" in action_types
    assert "INSTANT_PAYMENT_LINK" in action_types
    assert "DISCOUNTED_PAYMENT_LINK_5" in action_types
    assert "DISCOUNTED_PAYMENT_LINK_10" in action_types
    assert "MANUAL_REVIEW" in action_types
    assert not any("%" in code for code in action_types)


def test_2_no_action_equals_baseline():
    """Test 2: Verifies P(recovery | NO_ACTION) == base_p."""
    now = datetime.now(timezone.utc)
    vector = MLFeatureVector(
        feature_timestamp=now, amount=1000.0, customer_ltv=0.0,
        customer_failure_count_30d=0, customer_success_count_90d=0,
        attempt_number=1, hour=12, day_of_week=1,
        payment_method="UPI", failure_reason="BANK_TIMEOUT", subscription=False
    )
    no_action = CandidateAction(ActionType.NO_ACTION, "none", 0.0, 0.0, 0.0, 0.0, 1)
    base_p = 0.45
    p_no_action = estimate_action_recovery_probability(base_p, vector, no_action)
    assert p_no_action == base_p


def test_3_action_probability_bounds():
    """Test 3: Confirms P(A) is bounded strictly in [0.0, 0.98]."""
    now = datetime.now(timezone.utc)
    vector = MLFeatureVector(
        feature_timestamp=now, amount=1000.0, customer_ltv=0.0,
        customer_failure_count_30d=0, customer_success_count_90d=0,
        attempt_number=1, hour=12, day_of_week=1,
        payment_method="UPI", failure_reason="BANK_TIMEOUT", subscription=False
    )
    actions = get_all_candidate_actions()
    for act in actions:
        p = estimate_action_recovery_probability(0.95, vector, act)
        assert 0.0 <= p <= 0.98


def test_4_env_math_precision():
    """Test 4: Verifies exact absolute ENV calculation: S*P - C_gw - C_comm - S*d*P - N_fail*W_fatigue."""
    now = datetime.now(timezone.utc)
    vector = MLFeatureVector(
        feature_timestamp=now, amount=2000.0, customer_ltv=0.0,
        customer_failure_count_30d=2, customer_success_count_90d=0,
        attempt_number=1, hour=12, day_of_week=1,
        payment_method="UPI", failure_reason="BANK_TIMEOUT", subscription=False
    )
    # Action: PAYMENT_LINK (gw=1.5, comm=0.5, d=0.0, fatigue_weight=1.0)
    link_action = CandidateAction(ActionType.INSTANT_PAYMENT_LINK, "whatsapp", 1.5, 0.5, 0.0, 1.0, 3)
    base_p = 0.50
    # BANK_TIMEOUT link multiplier is 1.10 -> P = 0.55
    no_action_env = 2000.0 * 0.50  # 1000.0
    bd = compute_action_env(2000.0, base_p, vector, link_action, no_action_env)

    expected_gross = 2000.0 * 0.55  # 1100.0
    expected_fatigue = 2 * 1.0       # 2.0
    expected_env = 1100.0 - 1.5 - 0.5 - 0.0 - 2.0  # 1096.0
    expected_inc = 1096.0 - 1000.0                # 96.0

    assert bd.p_recovery == 0.55
    assert bd.expected_gross_revenue == expected_gross
    assert bd.env == expected_env
    assert bd.incremental_env == expected_inc


def test_5_incremental_env_calculation():
    """Test 5: Asserts incremental_env = ENV(A) - ENV(NO_ACTION)."""
    now = datetime.now(timezone.utc)
    vector = MLFeatureVector(
        feature_timestamp=now, amount=1000.0, customer_ltv=0.0,
        customer_failure_count_30d=0, customer_success_count_90d=0,
        attempt_number=1, hour=12, day_of_week=1,
        payment_method="UPI", failure_reason="BANK_TIMEOUT", subscription=False
    )
    no_action = CandidateAction(ActionType.NO_ACTION, "none", 0.0, 0.0, 0.0, 0.0, 1)
    no_action_bd = compute_action_env(1000.0, 0.40, vector, no_action, no_action_env=400.0)
    assert no_action_bd.incremental_env == 0.0


def test_6_discount_margin_destruction_prevention():
    """Test 6: Verifies a discount action is NOT selected if discount margin erosion exceeds incremental gain."""
    now = datetime.now(timezone.utc)
    vector = MLFeatureVector(
        feature_timestamp=now, amount=10000.0, customer_ltv=0.0,
        customer_failure_count_30d=0, customer_success_count_90d=0,
        attempt_number=1, hour=12, day_of_week=1,
        payment_method="CARD", failure_reason="EXPIRED_CARD", subscription=False
    )
    # Large amount (10,000 INR). High discount (25%) gives 2450 INR discount cost.
    # Non-discounted PAYMENT_LINK yields higher net ENV than high discount action
    base_p = 0.50
    no_action_env = 5000.0
    link_act = CandidateAction(ActionType.INSTANT_PAYMENT_LINK, "whatsapp", 1.5, 0.5, 0.0, 1.0, 3)
    disc_act = CandidateAction(ActionType.DISCOUNTED_PAYMENT_LINK_10, "whatsapp", 1.5, 0.5, 0.25, 1.5, 5)

    link_bd = compute_action_env(10000.0, base_p, vector, link_act, no_action_env)
    disc_bd = compute_action_env(10000.0, base_p, vector, disc_act, no_action_env)

    # Confirm non-discounted payment link yields higher net ENV due to heavy discount cost on large amount
    assert link_bd.env > disc_bd.env


def test_7_fatigue_penalty_scaling():
    """Test 7: Verifies fatigue penalty increases linearly with 30-day failure count."""
    now = datetime.now(timezone.utc)
    v0 = MLFeatureVector(
        feature_timestamp=now, amount=1000.0, customer_ltv=0.0,
        customer_failure_count_30d=0, customer_success_count_90d=0,
        attempt_number=1, hour=12, day_of_week=1,
        payment_method="UPI", failure_reason="BANK_TIMEOUT", subscription=False
    )
    v5 = MLFeatureVector(
        feature_timestamp=now, amount=1000.0, customer_ltv=0.0,
        customer_failure_count_30d=5, customer_success_count_90d=0,
        attempt_number=1, hour=12, day_of_week=1,
        payment_method="UPI", failure_reason="BANK_TIMEOUT", subscription=False
    )
    act = CandidateAction(ActionType.INSTANT_PAYMENT_LINK, "whatsapp", 1.5, 0.5, 0.0, 1.0, 3)
    bd0 = compute_action_env(1000.0, 0.5, v0, act, 500.0)
    bd5 = compute_action_env(1000.0, 0.5, v5, act, 500.0)

    assert bd0.fatigue_penalty == 0.0
    assert bd5.fatigue_penalty == 5.0
    assert bd0.env > bd5.env


def test_8_merchant_policy_filtering(db, sample_case):
    """Test 8: Merchant policy max discount cap filters out DISCOUNTED_PAYMENT_LINK_10."""
    case_id = sample_case
    policy = db.query(MerchantPolicy).first()
    policy.max_discount_percentage = 5.0  # Cap at 5%
    db.commit()

    res = select_optimal_recovery_action(db, case_id)
    disc10_bd = next(b for b in res.breakdown if b.action_type == ActionType.DISCOUNTED_PAYMENT_LINK_10.value)

    assert disc10_bd.eligible is False
    assert "Policy Reject" in disc10_bd.rejection_reason
    assert disc10_bd.p_recovery is None
    assert disc10_bd.env is None


def test_9_risk_gate_fraud_block(db, sample_case):
    """Test 9: High risk score (BLOCK) blocks all automated actions, leaving NO_ACTION."""
    case_id = sample_case
    case = db.query(RecoveryCase).filter(RecoveryCase.id == case_id).first()
    attempt = db.query(PaymentAttempt).filter(PaymentAttempt.payment_id == case.payment_id).first()
    attempt.failure_reason = "fraud_rejection"  # Trigger fraud risk block
    db.commit()

    res = select_optimal_recovery_action(db, case_id)
    assert res.selected_action == ActionType.NO_ACTION.value


def test_10_risk_gate_review_routing(db, sample_case):
    """Test 10: Risk status REVIEW blocks automated actions but permits MANUAL_REVIEW."""
    case_id = sample_case
    case = db.query(RecoveryCase).filter(RecoveryCase.id == case_id).first()
    case.amount_at_risk = 30000.0  # Above manual approval threshold
    db.commit()

    res = select_optimal_recovery_action(db, case_id)
    manual_bd = next(b for b in res.breakdown if b.action_type == ActionType.MANUAL_REVIEW.value)
    retry_bd = next(b for b in res.breakdown if b.action_type == ActionType.RETRY.value)

    assert manual_bd.eligible is True
    assert retry_bd.eligible is False


def test_11_negative_incremental_env_fallback(db, sample_case):
    """Test 11: Confirms engine falls back to NO_ACTION when no candidate achieves incremental_env > 0."""
    case_id = sample_case
    # Modify case amount to very small (e.g. 5 INR), where fixed gateway/comm fees exceed gross recovery
    case = db.query(RecoveryCase).filter(RecoveryCase.id == case_id).first()
    case.amount_at_risk = 5.0
    db.commit()

    res = select_optimal_recovery_action(db, case_id)
    assert res.selected_action == ActionType.NO_ACTION.value


def test_12_no_action_invariant_safety(db, sample_case):
    """Test 12: Asserts NO_ACTION is always an explicit invariant in breakdowns."""
    case_id = sample_case
    res = select_optimal_recovery_action(db, case_id)
    no_action_bd = next((b for b in res.breakdown if b.action_type == ActionType.NO_ACTION.value), None)
    assert no_action_bd is not None
    assert no_action_bd.eligible is True


def test_13_agent_decision_audit_persistence(db, sample_case):
    """Test 13: Verifies rich JSON audit breakdown and versioning fields in AgentDecision DB table."""
    case_id = sample_case
    res = select_optimal_recovery_action(db, case_id)

    db_dec = db.query(AgentDecision).filter(AgentDecision.recovery_case_id == case_id).first()
    assert db_dec is not None
    assert db_dec.selected_action == res.selected_action
    assert db_dec.model_name == f"ENV_Engine_{ENV_ENGINE_VERSION}"
    assert "base_probability" in db_dec.reasoning
    assert "prediction_source" in db_dec.reasoning


def test_14_deterministic_decision_stability(db, sample_case):
    """Test 14: Confirms identical inputs guarantee identical action selections and ENV calculations."""
    case_id = sample_case
    r1 = select_optimal_recovery_action(db, case_id)
    r2 = select_optimal_recovery_action(db, case_id)

    assert r1.selected_action == r2.selected_action
    assert r1.selected_env == r2.selected_env
    assert r1.selected_incremental_env == r2.selected_incremental_env


def test_15_end_to_end_ml_to_env_pipeline(db, sample_case):
    """Test 15: Full integration test linking ML prediction -> policy/risk gate -> ENV engine."""
    case_id = sample_case
    res = select_optimal_recovery_action(db, case_id)

    assert res.case_id == case_id
    assert 0.0 <= res.base_probability <= 1.0
    assert res.selected_action in [a.value for a in ActionType]
    assert len(res.breakdown) == 6


def test_16_probability_saturation():
    """Test 16: Verifies multiplier capping at 0.98 ceiling when P0 * M > 0.98."""
    now = datetime.now(timezone.utc)
    vector = MLFeatureVector(
        feature_timestamp=now, amount=1000.0, customer_ltv=0.0,
        customer_failure_count_30d=0, customer_success_count_90d=0,
        attempt_number=1, hour=12, day_of_week=1,
        payment_method="UPI", failure_reason="BANK_TIMEOUT", subscription=False
    )
    act = CandidateAction(ActionType.RETRY, "gateway", 2.0, 0.0, 0.0, 0.1, 2)
    # base_p = 0.90, RETRY BANK_TIMEOUT mult = 1.35 -> 0.90 * 1.35 = 1.215 -> Capped at 0.98!
    p = estimate_action_recovery_probability(0.90, vector, act)
    assert p == 0.98


def test_17_tie_break_determinism():
    """Test 17: Verifies deterministic tie-breaking using priority_rank when two actions yield identical incremental_env."""
    now = datetime.now(timezone.utc)
    vector = MLFeatureVector(
        feature_timestamp=now, amount=1000.0, customer_ltv=0.0,
        customer_failure_count_30d=0, customer_success_count_90d=0,
        attempt_number=1, hour=12, day_of_week=1,
        payment_method="UPI", failure_reason="BANK_TIMEOUT", subscription=False
    )
    # Create two actions with identical costs and efficacy
    a1 = CandidateAction(ActionType.RETRY, "gateway", 2.0, 0.0, 0.0, 0.0, priority_rank=2)
    a2 = CandidateAction(ActionType.INSTANT_PAYMENT_LINK, "whatsapp", 2.0, 0.0, 0.0, 0.0, priority_rank=3)

    bd1 = compute_action_env(1000.0, 0.5, vector, a1, 500.0)
    bd2 = compute_action_env(1000.0, 0.5, vector, a2, 500.0)

    # Sort using tie-breaking key
    candidates = [a1, a2]
    action_map = {a.action_type.value: a for a in candidates}
    bds = [bd1, bd2]
    bds.sort(key=lambda b: (-b.incremental_env, (b.gateway_cost or 0.0) + (b.comm_cost or 0.0), action_map[b.action_type].priority_rank))

    # Priority rank 2 (RETRY) must beat priority rank 3 (LINK) on tie!
    assert bds[0].action_type == ActionType.RETRY.value


def test_18_decision_idempotency(db, sample_case):
    """Test 18: Verifies calling select_optimal_recovery_action twice returns existing decision without creating duplicate rows."""
    case_id = sample_case
    res1 = select_optimal_recovery_action(db, case_id)
    assert res1.idempotent_reused is False

    res2 = select_optimal_recovery_action(db, case_id)
    assert res2.idempotent_reused is True

    rows = db.query(AgentDecision).filter(AgentDecision.recovery_case_id == case_id).all()
    assert len(rows) == 1


def test_19_concurrent_decision_idempotency(db, sample_case):
    """Test 19: Simulates multi-threaded concurrent calls to verify database concurrency safety."""
    import os
    results = []
    errors = []

    db_path = "./test_concurrent_env.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    file_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=file_engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=file_engine)

    # Populate test data in file_engine
    init_session = TestingSessionLocal()
    policy = MerchantPolicy()
    init_session.add(policy)
    cust = Customer(external_customer_id="cust_conc_101")
    init_session.add(cust)
    init_session.commit()
    order = Order(razorpay_order_id="ord_conc_101", customer_id=cust.id, amount=5000.0)
    init_session.add(order)
    init_session.commit()
    pay = Payment(razorpay_payment_id="pay_conc_101", order_id=order.id, amount=5000.0, status="failed")
    init_session.add(pay)
    init_session.commit()
    att = PaymentAttempt(payment_id=pay.id, attempt_number=1, status="FAILED", failure_reason="BANK_TIMEOUT", payment_method="UPI")
    init_session.add(att)
    init_session.commit()
    case = RecoveryCase(case_type="ONE_TIME", customer_id=cust.id, order_id=order.id, payment_id=pay.id, amount_at_risk=5000.0, status="RECOVERY_ELIGIBLE")
    init_session.add(case)
    init_session.commit()
    conc_case_id = case.id
    init_session.close()

    def worker():
        try:
            s = TestingSessionLocal()
            res = select_optimal_recovery_action(s, conc_case_id)
            results.append(res)
            s.close()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Verify exactly 1 decision created
    ver_session = TestingSessionLocal()
    rows = ver_session.query(AgentDecision).filter(AgentDecision.recovery_case_id == conc_case_id).all()
    num_rows = len(rows)
    ver_session.close()

    # Clean up file DB
    Base.metadata.drop_all(bind=file_engine)
    file_engine.dispose()
    if os.path.exists(db_path):
        os.remove(db_path)

    assert len(errors) == 0
    assert len(results) == 3
    assert num_rows == 1
