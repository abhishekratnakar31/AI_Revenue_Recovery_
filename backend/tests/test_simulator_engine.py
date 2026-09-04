"""
Milestone 5 Test Suite

Tests:
1. Persona Generation (Attribute boundaries, segment sampling).
2. Scenario Payload Structure (Razorpay JSON webhook payload compatibility).
3. Batch Simulation Execution (Entity creation, pipeline throughput, recovery outcomes).
4. Simulation Reproducibility (Identical outputs across runs with matching random seed).
"""

import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Set test environment
os.environ["USE_TEST_DB"] = "1"
os.environ["TEST_DATABASE_URL"] = "sqlite:///./test.db"

from backend.app.core.database import Base
from backend.app.models.models import Customer, Order, Payment, PaymentAttempt, RecoveryCase, Outcome
from simulation.personas import get_random_persona, PERSONA_PROFILES
from simulation.scenarios import get_random_scenario, generate_failed_webhook_payload, generate_captured_webhook_payload
from simulation.runner import run_simulation_batch

engine = create_engine("sqlite:///./test.db", connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def test_persona_generation():
    persona = get_random_persona(seed=42)
    assert persona is not None
    assert persona.name in [p.name for p in PERSONA_PROFILES.values()]
    assert 0.0 <= persona.responsiveness <= 1.0
    assert 0.0 <= persona.opt_out_prob <= 1.0
    assert persona.ltv_range[0] < persona.ltv_range[1]


def test_scenario_payload_structure():
    scen = get_random_scenario(seed=42)
    payload = generate_failed_webhook_payload(
        event_id="evt_test_501",
        order_id="ord_test_501",
        payment_id="pay_test_501",
        customer_id="cust_test_501",
        amount_inr=1500.0,
        scenario=scen
    )

    assert payload["event"] == "payment.failed"
    assert payload["event_id"] == "evt_test_501"

    entity = payload["payload"]["payment"]["entity"]
    assert entity["id"] == "pay_test_501"
    assert entity["order_id"] == "ord_test_501"
    assert entity["amount"] == 150000  # Amount in paisa
    assert entity["error_reason"] == scen.error_reason


def test_captured_payload_structure():
    payload = generate_captured_webhook_payload(
        event_id="evt_cap_501",
        order_id="ord_test_501",
        payment_id="pay_test_501",
        amount_inr=1500.0
    )
    assert payload["event"] == "payment.captured"
    entity = payload["payload"]["payment"]["entity"]
    assert entity["status"] == "captured"
    assert entity["amount"] == 150000


def test_batch_simulation_execution():
    db = TestingSessionLocal()
    summary = run_simulation_batch(db, num_cases=20, random_seed=123)

    assert summary["simulation_seed"] == 123
    assert summary["total_cases_generated"] == 20
    assert summary["total_amount_at_risk"] > 0
    assert "status_breakdown" in summary
    assert "persona_breakdown" in summary
    assert "scenario_breakdown" in summary

    # Verify database entities created
    assert db.query(Customer).count() > 0
    assert db.query(Order).count() == 20
    assert db.query(Payment).count() == 20
    assert db.query(PaymentAttempt).count() == 20
    assert db.query(RecoveryCase).count() == 20

    db.close()


def test_simulation_reproducibility():
    # Run 1
    db1 = TestingSessionLocal()
    summary1 = run_simulation_batch(db1, num_cases=30, random_seed=42)
    db1.close()

    # Reset DB tables
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    # Run 2 with identical seed
    db2 = TestingSessionLocal()
    summary2 = run_simulation_batch(db2, num_cases=30, random_seed=42)
    db2.close()

    # Compare exact numerical metrics
    assert summary1["total_cases_generated"] == summary2["total_cases_generated"]
    assert summary1["total_amount_at_risk"] == summary2["total_amount_at_risk"]
    assert summary1["total_recovered_amount"] == summary2["total_recovered_amount"]
    assert summary1["recovery_rate_pct"] == summary2["recovery_rate_pct"]
    assert summary1["status_breakdown"] == summary2["status_breakdown"]
    assert summary1["persona_breakdown"] == summary2["persona_breakdown"]
