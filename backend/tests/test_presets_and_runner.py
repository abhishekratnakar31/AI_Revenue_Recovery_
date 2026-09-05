"""
Standalone Rigorous Test Suite for Deterministic Presets, Simulation Runner, and Preset API.

Uses isolated SQLite in-memory database to verify 100% preset validation success,
action execution, notification status, stored experiment groups, and refund deductions.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.core.database import Base, get_db
from backend.app.models.models import MerchantPolicy, RefundEvent, Outcome, RecoveryCase
from simulation.presets import PRESETS, list_presets, get_preset
from simulation.preset_runner import run_preset, run_all_presets

# Isolated SQLite in-memory database engine with StaticPool for standalone multi-connection testing
TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_test_database():
    """Create fresh database schema and default merchant policy for each test."""
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()
    try:
        pol = MerchantPolicy(
            merchant_id=1,
            max_discount_percentage=15.0,
            max_retries=3,
            manual_approval_threshold=25000.0,
            version=1
        )
        db.add(pol)
        db.commit()
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=test_engine)
        app.dependency_overrides.pop(get_db, None)


def test_presets_list_registration():
    """Verify that all 7 presets are registered with correct attributes."""
    presets = list_presets()
    assert len(presets) == 7
    names = [p["name"] for p in presets]
    assert "BANK_TIMEOUT_RECOVERY" in names
    assert "CONFIRMED_HDFC_DEGRADATION" in names
    assert "BUDGET_DISCOUNT_RECOVERY" in names
    assert "HIGH_VALUE_MANUAL_REVIEW" in names
    assert "OPTED_OUT_CUSTOMER" in names
    assert "FRAUD_DECLINE_BLOCK" in names
    assert "REFUND_AFTER_RECOVERY" in names


def test_preset_getter():
    """Verify get_preset helper function."""
    preset = get_preset("BANK_TIMEOUT_RECOVERY")
    assert preset.customer_id == "preset_vip_timeout"
    assert preset.amount_inr == 2500.0

    with pytest.raises(KeyError):
        get_preset("NON_EXISTENT_PRESET")


@pytest.mark.parametrize("preset_key", list(PRESETS.keys()))
def test_all_7_presets_pass_validation(preset_key, setup_test_database):
    """
    Rigorously execute each of the 7 presets against isolated database
    and assert preset_validation['passed'] is True.
    """
    db = setup_test_database
    res = run_preset(preset_key, seed=42, db_session=db)
    
    val = res.get("preset_validation", {})
    assert val.get("passed") is True, f"Preset '{preset_key}' failed validation: {val}"
    assert val.get("match_action") is True
    assert val.get("match_outcome") is True
    assert val.get("match_group") is True
    assert val.get("match_notification") is True


def test_refund_preset_creates_attribution_deduction(setup_test_database):
    """Verify that REFUND_AFTER_RECOVERY preset creates a RefundEvent and updates Outcome."""
    db = setup_test_database
    res = run_preset("REFUND_AFTER_RECOVERY", seed=42, db_session=db)
    assert res["preset_validation"]["passed"] is True
    
    case_id = res["case_id"]
    outcome = db.query(Outcome).filter(Outcome.case_id == case_id).first()
    assert outcome is not None
    assert outcome.refund_deductions == 500.0

    refund_event = db.query(RefundEvent).filter(RefundEvent.razorpay_refund_id == "rfnd_refund_after_recovery").first()
    assert refund_event is not None
    assert refund_event.amount == 500.0


def test_preset_api_endpoints(setup_test_database):
    """Test FastAPI GET /api/v1/presets and POST /api/v1/presets/run."""
    # GET /api/v1/presets
    response = client.get("/api/v1/presets")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 7

    # POST /api/v1/presets/run (single preset)
    response = client.post("/api/v1/presets/run", json={"preset_name": "BANK_TIMEOUT_RECOVERY", "seed": 42})
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "completed"
    assert res_data["preset"] == "BANK_TIMEOUT_RECOVERY"
    assert res_data["result"]["preset_validation"]["passed"] is True

    # POST /api/v1/presets/run (all presets)
    response_all = client.post("/api/v1/presets/run", json={"seed": 42})
    assert response_all.status_code == 200
    res_all = response_all.json()
    assert res_all["status"] == "completed"
    assert res_all["total_presets"] == 7
    assert res_all["passed"] == 7
    assert res_all["failed"] == 0


def test_cases_api_search_filter(setup_test_database):
    """Test searching cases by external customer ID."""
    db = setup_test_database
    run_preset("BANK_TIMEOUT_RECOVERY", seed=42, db_session=db)

    response = client.get("/api/v1/cases?search=preset_vip_timeout")
    assert response.status_code == 200
    res = response.json()
    assert "items" in res
    assert res["total"] >= 1
