"""
Milestone 6 Test Suite

Tests:
1. Baseline Strategies Definition (Static retry, generic link, no intervention).
2. Experiment Creation (DB persistence of experiment metadata).
3. Assigner Determinism (Re-evaluating a case returns identical group assignment).
4. Assigner Split Ratio Distribution (Evaluates 1,000 cases to verify 50/45/5 split).
5. Experiment Metrics Aggregation (Computes group-wise recovery rates and revenue totals).
"""

import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sqlalchemy.pool import StaticPool
from backend.app.core.database import Base
from backend.app.models.models import Customer, RecoveryCase, Experiment, ExperimentAssignment, Outcome
from backend.app.experiments.baselines import get_baseline_action, BASELINE_STRATEGIES
from backend.app.experiments.assigner import assign_case_to_experiment
from backend.app.experiments.registry import get_or_create_experiment, get_experiment_metrics

ab_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=ab_engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=ab_engine)
    yield


def test_baseline_strategies_definition():
    static_retry = get_baseline_action("STATIC_RETRY")
    assert static_retry.strategy_name == "STATIC_RETRY"
    assert static_retry.action_type == "RETRY"
    assert static_retry.delay_minutes == 1440

    generic_link = get_baseline_action("GENERIC_PAYMENT_LINK")
    assert generic_link.strategy_name == "GENERIC_PAYMENT_LINK"
    assert generic_link.action_type == "PAYMENT_LINK"
    assert generic_link.channel == "email"

    no_action = get_baseline_action("NO_INTERVENTION")
    assert no_action.action_type == "NO_ACTION"


def test_experiment_creation():
    db = TestingSessionLocal()
    exp = get_or_create_experiment(db, name="test_ab_exp", seed=42)
    assert exp is not None
    assert exp.name == "test_ab_exp"
    assert exp.random_seed == 42

    # Verify DB persistence
    assert db.query(Experiment).count() == 1
    db.close()


def test_assigner_determinism():
    db = TestingSessionLocal()
    cust = Customer(external_customer_id="cust_det_test")
    db.add(cust)
    db.commit()

    case = RecoveryCase(case_type="payment_failure", customer_id=cust.id, amount_at_risk=2000.0, status="RECOVERY_ELIGIBLE")
    db.add(case)
    db.commit()

    # First assignment
    res1 = assign_case_to_experiment(db, case.id, experiment_name="test_det", seed=42)
    assert res1.is_new_assignment is True

    # Re-evaluate 5 times
    for _ in range(5):
        res = assign_case_to_experiment(db, case.id, experiment_name="test_det", seed=42)
        assert res.is_new_assignment is False
        assert res.group == res1.group

    db.close()


def test_assigner_split_ratio_distribution():
    db = TestingSessionLocal()
    cust = Customer(external_customer_id="cust_ratio_test")
    db.add(cust)
    db.commit()

    group_counts = {"TREATMENT": 0, "CONTROL": 0, "NO_INTERVENTION": 0}

    # Evaluate 1,000 synthetic cases
    for case_id in range(1, 1001):
        res = assign_case_to_experiment(db, case_id=case_id, experiment_name="test_ratio_split", seed=42)
        group_counts[res.group] += 1

    # Verify expected distribution: Treatment ~50% (450-550), Control ~45% (400-500), No-Intervention ~5% (20-80)
    assert 440 <= group_counts["TREATMENT"] <= 560
    assert 400 <= group_counts["CONTROL"] <= 500
    assert 20 <= group_counts["NO_INTERVENTION"] <= 80

    db.close()


def test_experiment_metrics_aggregation():
    db = TestingSessionLocal()
    cust = Customer(external_customer_id="cust_metrics_test")
    db.add(cust)
    db.commit()

    exp = get_or_create_experiment(db, name="test_metrics_exp", seed=42)

    # Create 3 cases, 1 per group
    for i, grp in enumerate(["TREATMENT", "CONTROL", "NO_INTERVENTION"], start=1):
        case = RecoveryCase(case_type="payment_failure", customer_id=cust.id, amount_at_risk=1000.0 * i, status="RECOVERY_ELIGIBLE")
        db.add(case)
        db.commit()

        assignment = ExperimentAssignment(experiment_id=exp.id, case_id=case.id, group=grp)
        db.add(assignment)

        # Mark Treatment case as recovered
        if grp == "TREATMENT":
            outcome = Outcome(case_id=case.id, intervention="AI_ACTION", payment_success=True, gross_recovered=1000.0, net_recovered=1000.0, attribution_status="DIRECT")
            db.add(outcome)
        db.commit()

    metrics = get_experiment_metrics(db, exp.id)
    assert metrics["total_assignments"] == 3

    treatment_metrics = metrics["group_metrics"]["TREATMENT"]
    assert treatment_metrics["total_cases"] == 1
    assert treatment_metrics["recovered_cases"] == 1
    assert treatment_metrics["recovery_rate_pct"] == 100.0
    assert treatment_metrics["total_gross_recovered"] == 1000.0

    control_metrics = metrics["group_metrics"]["CONTROL"]
    assert control_metrics["total_cases"] == 1
    assert control_metrics["recovered_cases"] == 0
    assert control_metrics["recovery_rate_pct"] == 0.0

    db.close()
