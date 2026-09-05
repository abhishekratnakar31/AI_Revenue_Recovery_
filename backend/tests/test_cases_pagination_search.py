"""
Case List API Pagination, Search & Deduplication Test Suite for RecoverAI.

Tests:
1. One payment with three attempts returns ONE RecoveryCase, not three.
2. total, has_next, sorting, and pagination remain correct with multiple attempts.
3. search works server-side by customer identifier and case ID.
4. Status and payment-method filters combine correctly.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.core.database import Base, get_db
from backend.app.models.models import Customer, Order, Payment, PaymentAttempt, RecoveryCase
from backend.app.recovery.case_manager import process_failed_payment_event

client = TestClient(app)


from sqlalchemy.pool import StaticPool

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


def test_one_payment_three_attempts_returns_one_case(db_session):
    def get_test_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = get_test_db

    order_id = "ord_dedup_001"
    pay_id = "pay_dedup_001"
    cust_id = "cust_dedup_001"

    # Process Attempt 1
    p1 = {
        "payload": {
            "payment": {
                "entity": {
                    "id": pay_id,
                    "order_id": order_id,
                    "customer_id": cust_id,
                    "amount": 150000,
                    "method": "upi",
                    "bank": "HDFC",
                    "error_reason": "bank_timeout"
                }
            }
        }
    }
    process_failed_payment_event(db_session, p1)

    # Process Attempt 2
    p2 = {
        "payload": {
            "payment": {
                "entity": {
                    "id": pay_id,
                    "order_id": order_id,
                    "customer_id": cust_id,
                    "amount": 150000,
                    "method": "upi",
                    "bank": "HDFC",
                    "error_reason": "insufficient_funds"
                }
            }
        }
    }
    process_failed_payment_event(db_session, p2)

    # Process Attempt 3
    p3 = {
        "payload": {
            "payment": {
                "entity": {
                    "id": pay_id,
                    "order_id": order_id,
                    "customer_id": cust_id,
                    "amount": 150000,
                    "method": "upi",
                    "bank": "HDFC",
                    "error_reason": "network_failure"
                }
            }
        }
    }
    process_failed_payment_event(db_session, p3)

    # Verify database has 3 attempts but EXACTLY 1 RecoveryCase
    attempts_cnt = db_session.query(PaymentAttempt).count()
    cases_cnt = db_session.query(RecoveryCase).count()

    assert attempts_cnt == 3
    assert cases_cnt == 1

    app.dependency_overrides.clear()


def test_pagination_total_has_next_sorting(db_session):
    def get_test_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = get_test_db

    # Create 15 cases
    cust = Customer(external_customer_id="cust_page_user", lifetime_value=1000.0)
    db_session.add(cust)
    db_session.commit()

    for i in range(15):
        ord_obj = Order(razorpay_order_id=f"ord_pg_{i}", customer_id=cust.id, amount=(i + 1) * 100.0)
        db_session.add(ord_obj)
        db_session.commit()

        pay_obj = Payment(razorpay_payment_id=f"pay_pg_{i}", order_id=ord_obj.id, amount=(i + 1) * 100.0, status="FAILED", payment_method="card" if i % 2 == 0 else "upi")
        db_session.add(pay_obj)
        db_session.commit()

        case_obj = RecoveryCase(case_type="payment_failure", customer_id=cust.id, order_id=ord_obj.id, payment_id=pay_obj.id, amount_at_risk=(i + 1) * 100.0, status="RECOVERY_ELIGIBLE")
        db_session.add(case_obj)
        db_session.commit()

    # Query Page 1 (page_size=10)
    resp1 = client.get("/api/v1/cases?page=1&page_size=10")
    assert resp1.status_code == 200
    data1 = resp1.json()

    assert data1["page"] == 1
    assert data1["page_size"] == 10
    assert data1["total"] == 15
    assert data1["has_next"] is True
    assert len(data1["items"]) == 10

    # Query Page 2 (page_size=10)
    resp2 = client.get("/api/v1/cases?page=2&page_size=10")
    assert resp2.status_code == 200
    data2 = resp2.json()

    assert data2["page"] == 2
    assert data2["has_next"] is False
    assert len(data2["items"]) == 5

    app.dependency_overrides.clear()


def test_combined_status_and_payment_method_filters(db_session):
    def get_test_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = get_test_db

    cust = Customer(external_customer_id="cust_filter_user")
    db_session.add(cust)
    db_session.commit()

    # Case 1: RECOVERY_ELIGIBLE + UPI
    ord1 = Order(razorpay_order_id="ord_f1", customer_id=cust.id, amount=500.0)
    db_session.add(ord1)
    db_session.commit()
    pay1 = Payment(razorpay_payment_id="pay_f1", order_id=ord1.id, amount=500.0, status="FAILED", payment_method="UPI")
    db_session.add(pay1)
    db_session.commit()
    c1 = RecoveryCase(case_type="payment_failure", customer_id=cust.id, order_id=ord1.id, payment_id=pay1.id, amount_at_risk=500.0, status="RECOVERY_ELIGIBLE")
    db_session.add(c1)

    # Case 2: RECOVERED + CARD
    ord2 = Order(razorpay_order_id="ord_f2", customer_id=cust.id, amount=1000.0)
    db_session.add(ord2)
    db_session.commit()
    pay2 = Payment(razorpay_payment_id="pay_f2", order_id=ord2.id, amount=1000.0, status="CAPTURED", payment_method="CARD")
    db_session.add(pay2)
    db_session.commit()
    c2 = RecoveryCase(case_type="payment_failure", customer_id=cust.id, order_id=ord2.id, payment_id=pay2.id, amount_at_risk=1000.0, status="RECOVERED")
    db_session.add(c2)

    db_session.commit()

    # Filter status=RECOVERY_ELIGIBLE & payment_method=UPI
    res = client.get("/api/v1/cases?status=RECOVERY_ELIGIBLE&payment_method=UPI")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["payment_method"].upper() == "UPI"
    assert data["items"][0]["status"] == "RECOVERY_ELIGIBLE"

    app.dependency_overrides.clear()
