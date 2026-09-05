"""
Merchant Policy Scoping, Concurrency Isolation & Audit Test Suite for RecoverAI.

Tests:
1. Correct merchant policy is resolved for each merchant.
2. Optimistic-lock conflict returns 409 and does NOT partially update policy.
3. Policy update creates an audit entry in audit_logs table.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.core.database import Base, get_db
from backend.app.models.models import MerchantPolicy, AuditLog
from backend.app.api.v1.policy_api import _get_or_create_merchant_policy

client = TestClient(app)


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


def test_merchant_policy_resolution_scoping(db_session):
    p1 = MerchantPolicy(merchant_id=1, max_retries=3, max_discount_percentage=5.0, version=1)
    p2 = MerchantPolicy(merchant_id=2, max_retries=5, max_discount_percentage=15.0, version=1)
    db_session.add_all([p1, p2])
    db_session.commit()

    pol1 = _get_or_create_merchant_policy(db_session, merchant_id=1)
    pol2 = _get_or_create_merchant_policy(db_session, merchant_id=2)

    assert pol1.max_retries == 3
    assert pol1.max_discount_percentage == 5.0

    assert pol2.max_retries == 5
    assert pol2.max_discount_percentage == 15.0


def test_optimistic_locking_conflict_409(db_session):
    def get_test_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = get_test_db

    policy = MerchantPolicy(merchant_id=1, max_retries=3, max_discount_percentage=5.0, version=5)
    db_session.add(policy)
    db_session.commit()

    # Attempt to update policy using outdated expected_version = 4 (current is 5)
    payload = {
        "expected_version": 4,
        "max_retries": 5,
        "max_discount_percentage": 10.0
    }

    response = client.post(
        "/api/v1/policy",
        json=payload,
        headers={"Authorization": "Bearer merchant_secret_key"}
    )

    assert response.status_code == 409
    data = response.json()
    assert "CONFLICT" in data["detail"].upper() or "VERSION" in data["detail"].upper()

    # Verify policy was NOT updated
    db_session.refresh(policy)
    assert policy.version == 5
    assert policy.max_retries == 3

    app.dependency_overrides.clear()


def test_policy_update_creates_audit_log_entry(db_session):
    def get_test_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = get_test_db

    policy = MerchantPolicy(merchant_id=1, max_retries=3, max_discount_percentage=5.0, version=1)
    db_session.add(policy)
    db_session.commit()

    payload = {
        "expected_version": 1,
        "max_retries": 4,
        "max_discount_percentage": 8.0
    }

    response = client.post(
        "/api/v1/policy",
        json=payload,
        headers={"Authorization": "Bearer merchant_secret_key"}
    )

    assert response.status_code == 200
    updated_data = response.json()
    assert updated_data["version"] == 2
    assert updated_data["max_retries"] == 4

    # Verify AuditLog created
    audit = db_session.query(AuditLog).filter(AuditLog.event == "POLICY_UPDATED").first()
    assert audit is not None
    assert audit.actor == "MERCHANT_ADMIN"
    assert "v1" in str(audit.previous_state) or "1" in str(audit.previous_state)
    assert "v2" in str(audit.new_state) or "2" in str(audit.new_state)

    app.dependency_overrides.clear()
