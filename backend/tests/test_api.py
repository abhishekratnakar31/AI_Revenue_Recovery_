"""
RecoverAI Milestone 13 API Test Suite (/api/v1).

Comprehensive unit and integration tests for all REST API endpoints:
- Dashboard Summary & String-Decimal Financial Precision
- Mandatory experiment_id for Attribution & 30s TTL Cache
- Gateway Route Degradation Diagnostics & Policy Rules
- Paginated Case Listing with Metadata, Filtering, & Sorting
- Decision Audit Timeline Projection (M8 Selection vs M11 Guardrail)
- Optimistic Concurrency Control (Atomic Versioning 409, Range Validation 422, Audit Log, Bearer Auth)
"""

import pytest
import datetime
import uuid
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.database import Base, get_db
from backend.app.main import app
from backend.app.models.models import (
    Customer, Order, Payment, PaymentAttempt, RecoveryCase, Experiment, ExperimentAssignment, Outcome,
    GatewayRouteStatus, MerchantPolicy, AuditLog, ModelPrediction, AgentDecision, PolicyDecision, RecoveryAction
)
from backend.app.api.v1.attribution_api import clear_attribution_cache


@pytest.fixture
def db():
    """Provides a clean in-memory SQLite database session for API unit tests."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def client(db):
    """Provides a FastAPI TestClient with overridden get_db dependency."""
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    clear_attribution_cache()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def create_sample_experiment_data(db):
    """Helper to populate an experiment with CONTROL and TREATMENT cases."""
    exp = Experiment(name="Test Experiment v1", dataset_version="v1.0")
    db.add(exp)
    db.commit()

    for i in range(10):
        uid = uuid.uuid4().hex[:8]
        cust = Customer(external_customer_id=f"cust_{uid}", lifetime_value=50000.0)
        db.add(cust)
        db.commit()

        order = Order(razorpay_order_id=f"ord_{uid}", customer_id=cust.id, amount=10000.0, currency="INR")
        db.add(order)
        db.commit()

        pay = Payment(razorpay_payment_id=f"pay_{uid}", order_id=order.id, amount=10000.0, status="FAILED", payment_method="UPI")
        db.add(pay)
        db.commit()

        att = PaymentAttempt(
            payment_id=pay.id, attempt_number=1, status="failed", gateway="razorpay", payment_method="UPI", bank="HDFC", failure_reason="BANK_TIMEOUT"
        )
        db.add(att)
        db.commit()

        is_recovered = (i < 4)
        case = RecoveryCase(
            case_type="payment_failure", customer_id=cust.id, order_id=order.id, payment_id=pay.id, amount_at_risk=10000.0, status="RECOVERED" if is_recovered else "RECOVERY_ACTIVE"
        )
        db.add(case)
        db.commit()

        asgn = ExperimentAssignment(experiment_id=exp.id, case_id=case.id, group="CONTROL" if i < 5 else "TREATMENT")
        db.add(asgn)
        db.commit()

        outcome = Outcome(
            case_id=case.id,
            intervention="RETRY" if is_recovered else "NONE",
            payment_success=is_recovered,
            is_recovered=is_recovered,
            gross_recovered=10000.0 if is_recovered else 0.0,
            net_recovered=9900.0 if is_recovered else 0.0,
            gateway_cost=100.0 if is_recovered else 0.0,
            attribution_status="DIRECT" if is_recovered else "NONE",
        )
        db.add(outcome)
        db.commit()

    return exp


# --- 1. Operational & Root Endpoints ---
def test_read_root(client):
    res = client.get("/")
    assert res.status_code == 200
    assert res.json()["status"] == "running"


def test_health_check(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


# --- 2. Dashboard Summary API ---
def test_dashboard_summary_success(client, db):
    exp = create_sample_experiment_data(db)
    res = client.get(f"/api/v1/dashboard/summary?experiment_id={exp.id}")
    assert res.status_code == 200
    data = res.json()
    assert data["experiment_id"] == exp.id
    assert "amount_at_risk" in data
    assert isinstance(data["amount_at_risk"], str)
    assert data["currency"] == "INR"


def test_dashboard_summary_financial_string_precision(client, db):
    exp = create_sample_experiment_data(db)
    res = client.get(f"/api/v1/dashboard/summary?experiment_id={exp.id}")
    data = res.json()
    # Verify monetary values are returned as formatted string decimals
    assert "." in data["amount_at_risk"]
    assert "." in data["cash_collected"]
    assert "." in data["incremental_net_revenue"]


# --- 3. Attribution Report API ---
def test_attribution_report_requires_experiment_id(client):
    res = client.get("/api/v1/attribution/report")
    assert res.status_code == 422  # Missing mandatory query param


def test_attribution_report_not_found(client):
    res = client.get("/api/v1/attribution/report?experiment_id=99999")
    assert res.status_code == 404


def test_attribution_report_success(client, db):
    exp = create_sample_experiment_data(db)
    res = client.get(f"/api/v1/attribution/report?experiment_id={exp.id}")
    assert res.status_code == 200
    data = res.json()
    assert data["experiment_id"] == exp.id
    assert "recovery_effect" in data
    assert "financial_effect" in data
    assert "srm_check" in data
    assert data["currency"] == "INR"
    assert isinstance(data["financial_effect"]["incremental_net_revenue"], str)


def test_attribution_report_ttl_caching(client, db):
    exp = create_sample_experiment_data(db)
    # First call populates cache
    res1 = client.get(f"/api/v1/attribution/report?experiment_id={exp.id}")
    # Second call returns cached result fast
    res2 = client.get(f"/api/v1/attribution/report?experiment_id={exp.id}")
    assert res1.json() == res2.json()


# --- 4. Gateway Route Degradation API ---
def test_degradation_routes_empty(client):
    res = client.get("/api/v1/degradation/routes")
    assert res.status_code == 200
    assert res.json()["total_routes"] == 0


def test_degradation_routes_with_data(client, db):
    route = GatewayRouteStatus(
        gateway="razorpay", payment_method="UPI", bank="HDFC", status="CONFIRMED", current_failure_rate=1.0, current_z_score=15.2, total_attempts=50, failed_attempts=50
    )
    db.add(route)
    db.commit()

    res = client.get("/api/v1/degradation/routes")
    assert res.status_code == 200
    data = res.json()
    assert data["total_routes"] == 1
    assert data["degraded_count"] == 1
    r_item = data["routes"][0]
    assert r_item["status"] == "CONFIRMED"
    assert len(r_item["policy_rules"]) > 0
    assert r_item["policy_rules"][0]["action_type"] == "RETRY"
    assert r_item["policy_rules"][0]["permission"] == "BLOCKED"


def test_degradation_routes_status_filter(client, db):
    r1 = GatewayRouteStatus(gateway="razorpay", payment_method="UPI", bank="HDFC", status="CONFIRMED")
    r2 = GatewayRouteStatus(gateway="razorpay", payment_method="CARD", bank="ICICI", status="NORMAL")
    db.add_all([r1, r2])
    db.commit()

    res = client.get("/api/v1/degradation/routes?status_filter=CONFIRMED")
    data = res.json()
    assert data["total_routes"] == 1
    assert data["routes"][0]["status"] == "CONFIRMED"


# --- 5. Cases List & Pagination API ---
def test_cases_list_pagination_metadata(client, db):
    exp = create_sample_experiment_data(db)
    res = client.get("/api/v1/cases?page=1&page_size=5")
    assert res.status_code == 200
    data = res.json()
    assert len(data["items"]) == 5
    assert data["page"] == 1
    assert data["page_size"] == 5
    assert data["total"] == 10
    assert data["has_next"] is True


def test_cases_list_sorting_and_filtering(client, db):
    exp = create_sample_experiment_data(db)
    res = client.get("/api/v1/cases?status=RECOVERED&sort_by=amount_at_risk&sort_order=desc")
    assert res.status_code == 200
    data = res.json()
    for item in data["items"]:
        assert item["status"] == "RECOVERED"


# --- 6. Case Details & Timeline API ---
def test_case_detail_success(client, db):
    exp = create_sample_experiment_data(db)
    case = db.query(RecoveryCase).first()
    res = client.get(f"/api/v1/cases/{case.id}")
    assert res.status_code == 200
    assert res.json()["case_id"] == case.id


def test_case_detail_not_found(client):
    res = client.get("/api/v1/cases/99999")
    assert res.status_code == 404


def test_case_timeline_steps(client, db):
    exp = create_sample_experiment_data(db)
    case = db.query(RecoveryCase).first()

    # Add predictions, decisions, actions for rich timeline
    pred = ModelPrediction(recovery_case_id=case.id, model_name="xgb", model_version="v1", prediction=0.85, feature_version="f1")
    agent_dec = AgentDecision(recovery_case_id=case.id, selected_action="RETRY", confidence_score=0.9)
    pol_dec = PolicyDecision(recovery_case_id=case.id, action_type="RETRY", decision="ALLOW", reason="NORMAL_ROUTE")
    act = RecoveryAction(recovery_case_id=case.id, action_type="RETRY", idempotency_key=f"act_{case.id}", status="EXECUTED")
    db.add_all([pred, agent_dec, pol_dec, act])
    db.commit()

    res = client.get(f"/api/v1/cases/{case.id}/timeline")
    assert res.status_code == 200
    data = res.json()
    assert data["case_id"] == case.id
    steps = data["steps"]
    step_types = [s["step_type"] for s in steps]

    assert "PAYMENT_ATTEMPT" in step_types
    assert "ML_RISK" in step_types
    assert "M8_AGENT_DECISION" in step_types
    assert "M11_ROUTE_GUARDRAIL" in step_types
    assert "M9_ACTION_EXECUTION" in step_types
    assert "M12_FINANCIAL_OUTCOME" in step_types


# --- 7. Merchant Policy API & Optimistic Concurrency ---
def test_policy_get_default(client, db):
    res = client.get("/api/v1/policy")
    assert res.status_code == 200
    data = res.json()
    assert data["version"] == 1
    assert data["max_retries"] == 2


def test_policy_update_requires_auth(client):
    res = client.post("/api/v1/policy", json={"expected_version": 1, "max_retries": 1})
    assert res.status_code == 401  # Requires Bearer token


def test_policy_update_success(client, db):
    res = client.post(
        "/api/v1/policy",
        headers={"Authorization": "Bearer merchant_secret_key"},
        json={"expected_version": 1, "max_retries": 3, "max_discount_percentage": 15.0}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["version"] == 2
    assert data["max_retries"] == 3
    assert data["max_discount_percentage"] == 15.0

    # Verify AuditLog recorded
    audit = db.query(AuditLog).filter(AuditLog.event == "POLICY_UPDATED").first()
    assert audit is not None
    assert audit.actor == "MERCHANT_ADMIN"


def test_policy_update_validation_error_422(client):
    res = client.post(
        "/api/v1/policy",
        headers={"Authorization": "Bearer merchant_secret_key"},
        json={"expected_version": 1, "max_discount_percentage": 50.0}  # Limit is 25.0%
    )
    assert res.status_code == 422


def test_policy_update_concurrency_conflict_409(client, db):
    # First update succeeds, advancing version from 1 to 2
    res1 = client.post(
        "/api/v1/policy",
        headers={"Authorization": "Bearer merchant_secret_key"},
        json={"expected_version": 1, "max_retries": 3}
    )
    assert res1.status_code == 200

    # Concurrent session tries to update with stale version 1 -> 409 Conflict
    res2 = client.post(
        "/api/v1/policy",
        headers={"Authorization": "Bearer merchant_secret_key"},
        json={"expected_version": 1, "max_retries": 4}
    )
    assert res2.status_code == 409
    assert "version conflict" in res2.json()["detail"].lower()


# --- 8. Simulation API ---
def test_simulation_run_endpoint(client, db):
    res = client.post("/api/v1/simulation/run", json={"num_cases": 5, "random_seed": 42})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "completed"
    assert data["cases_processed"] == 5
