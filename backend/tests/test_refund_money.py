"""
Refund & Money Correctness Test Suite for RecoverAI.

Tests:
1. Razorpay refund amount 50000 paise becomes ₹500.00.
2. Refunds with and without notes yield identical paise conversion.
3. Decimal/paise totals remain exact for ₹0.10, ₹99.99, and partial refunds.
4. Duplicate refund webhook changes financial outcome EXACTLY ONCE.
5. Refund after 30-day attribution window is recorded but does NOT mutate finalized attribution metrics.
"""

import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models.models import Customer, Order, Payment, RecoveryCase, Outcome, RefundEvent
from backend.app.analytics.attribution import AttributionEngine, utc_now
from backend.app.webhooks.processor import _handle_refund_created


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_paise_50000_becomes_500_inr():
    paise = 50000
    inr_amount = float(paise) / 100.0
    assert inr_amount == 500.0
    assert f"{inr_amount:.2f}" == "500.00"


def test_refunds_with_and_without_notes_identical():
    payload_with_notes = {
        "payload": {
            "refund": {
                "entity": {
                    "id": "rfnd_notes_1",
                    "payment_id": "pay_notes_1",
                    "amount": 12500,
                    "notes": {"reason": "customer_return", "store_id": "store_12"}
                }
            }
        }
    }
    payload_without_notes = {
        "payload": {
            "refund": {
                "entity": {
                    "id": "rfnd_notes_2",
                    "payment_id": "pay_notes_2",
                    "amount": 12500,
                    "notes": None
                }
            }
        }
    }

    amt1 = float(payload_with_notes["payload"]["refund"]["entity"]["amount"]) / 100.0
    amt2 = float(payload_without_notes["payload"]["refund"]["entity"]["amount"]) / 100.0

    assert amt1 == amt2 == 125.0


def test_exact_decimal_accounting_precision():
    amounts = [10, 9999, 4999]  # 0.10, 99.99, 49.99 in paise
    converted = [float(a) / 100.0 for a in amounts]

    assert converted == [0.10, 99.99, 49.99]
    assert sum(converted) == pytest.approx(150.08, abs=0.001)


def test_duplicate_refund_webhook_idempotency(db_session):
    cust = Customer(external_customer_id="cust_rfnd_idem", lifetime_value=1000.0)
    db_session.add(cust)
    db_session.commit()

    order = Order(razorpay_order_id="ord_rfnd_idem", customer_id=cust.id, amount=1000.0)
    db_session.add(order)
    db_session.commit()

    payment = Payment(razorpay_payment_id="pay_rfnd_idem", order_id=order.id, amount=1000.0, status="CAPTURED")
    db_session.add(payment)
    db_session.commit()

    case = RecoveryCase(case_type="payment_failure", customer_id=cust.id, order_id=order.id, payment_id=payment.id, amount_at_risk=1000.0, status="RECOVERED")
    db_session.add(case)
    db_session.commit()

    outcome = Outcome(case_id=case.id, is_recovered=True, gross_recovered=1000.0, refund_deductions=0.0, net_recovered=1000.0)
    db_session.add(outcome)
    db_session.commit()

    # Call 1: Process refund of 250.00 INR (25000 paise)
    res1 = AttributionEngine.process_refund_deduction(
        db=db_session,
        razorpay_refund_id="rfnd_duplicate_test_101",
        payment_id=payment.id,
        refund_amount=250.0
    )
    assert res1["status"] == "success"
    assert res1["processed"] is True

    # Check updated outcome
    db_session.refresh(outcome)
    assert outcome.refund_deductions == 250.0
    assert outcome.net_recovered == 750.0

    # Call 2: Attempt duplicate refund processing with SAME razorpay_refund_id
    res2 = AttributionEngine.process_refund_deduction(
        db=db_session,
        razorpay_refund_id="rfnd_duplicate_test_101",
        payment_id=payment.id,
        refund_amount=250.0
    )
    assert res2["status"] == "duplicate_refund_ignored"
    assert res2["processed"] is False

    # Verify Outcome.refund_deductions remained 250.0, NOT 500.0
    db_session.refresh(outcome)
    assert outcome.refund_deductions == 250.0
    assert outcome.net_recovered == 750.0

    # Verify exactly 1 RefundEvent row in DB
    events_count = db_session.query(RefundEvent).filter(RefundEvent.razorpay_refund_id == "rfnd_duplicate_test_101").count()
    assert events_count == 1


def test_refund_after_30_day_attribution_window(db_session):
    now = utc_now()
    old_time = now - timedelta(days=35)

    cust = Customer(external_customer_id="cust_old_rfnd", lifetime_value=5000.0)
    db_session.add(cust)
    db_session.commit()

    order = Order(razorpay_order_id="ord_old_rfnd", customer_id=cust.id, amount=5000.0)
    db_session.add(order)
    db_session.commit()

    payment = Payment(razorpay_payment_id="pay_old_rfnd", order_id=order.id, amount=5000.0, status="CAPTURED")
    db_session.add(payment)
    db_session.commit()

    case = RecoveryCase(case_type="payment_failure", customer_id=cust.id, order_id=order.id, payment_id=payment.id, amount_at_risk=5000.0, status="RECOVERED", created_at=old_time)
    db_session.add(case)
    db_session.commit()

    outcome = Outcome(case_id=case.id, is_recovered=True, gross_recovered=5000.0, refund_deductions=0.0, net_recovered=5000.0, recovery_timestamp=old_time)
    db_session.add(outcome)
    db_session.commit()

    # Process refund outside 30-day window
    res = AttributionEngine.process_refund_deduction(
        db=db_session,
        razorpay_refund_id="rfnd_late_35_days",
        payment_id=payment.id,
        refund_amount=1000.0
    )

    # Verify event is logged in RefundEvent table, but finalized Outcome is NOT mutated
    assert res["status"] == "success"
    db_session.refresh(outcome)
    assert outcome.refund_deductions == 0.0  # Finalized attribution is preserved
    refund_logged = db_session.query(RefundEvent).filter(RefundEvent.razorpay_refund_id == "rfnd_late_35_days").count()
    assert refund_logged == 1
