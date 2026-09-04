"""
Dedicated PostgreSQL Concurrency & Duplicate Refund Idempotency Test Suite for Milestone 12.

Verifies 5-thread concurrent worker refund ingestion safety under native PostgreSQL database transactions,
UNIQUE(razorpay_refund_id) constraint locking, and exact non-double-counted net revenue deduction semantics.
"""

import os
import time
import pytest
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.core.config import settings
from backend.app.models.models import (
    Customer,
    Order,
    Payment,
    PaymentAttempt,
    RecoveryCase,
    Outcome,
    RefundEvent,
    AuditLog,
)
from backend.app.analytics.attribution import AttributionEngine, utc_now


PG_URL = os.getenv("PG_DATABASE_URL", settings.DATABASE_URL)


def is_postgres_available() -> bool:
    try:
        eng = create_engine(PG_URL, connect_args={"connect_timeout": 3})
        with eng.connect() as conn:
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not is_postgres_available(),
    reason="PostgreSQL database is not reachable at PG_DATABASE_URL or settings.DATABASE_URL",
)


def test_postgres_5_thread_concurrent_duplicate_refund_idempotency():
    """
    Test 5 concurrent worker threads attempting to process the EXACT SAME razorpay_refund_id simultaneously against PostgreSQL.
    Verifies that native PostgreSQL UNIQUE(razorpay_refund_id) constraint results in:
    1. EXACTLY 1 thread returning status='success' (processed=True)
    2. 4 threads returning status='duplicate_refund_ignored' (processed=False)
    3. EXACTLY 1 RefundEvent row created in PostgreSQL
    4. Outcome.refund_deductions is updated EXACTLY ONCE (₹2,500.00, NOT ₹12,500.00)
    """
    pg_engine = create_engine(PG_URL, pool_pre_ping=True)
    Base.metadata.drop_all(bind=pg_engine)
    Base.metadata.create_all(bind=pg_engine)
    PGSession = sessionmaker(autocommit=False, autoflush=False, bind=pg_engine)

    db = PGSession()

    # Step 1: Pre-populate PostgreSQL with Customer, Order, Payment, RecoveryCase, and Outcome
    cust = Customer(external_customer_id="cust_pg_m12_concurrent", lifetime_value=50000.0)
    db.add(cust)
    db.commit()

    order = Order(razorpay_order_id="ord_pg_m12_concurrent", customer_id=cust.id, amount=10000.0, currency="INR")
    db.add(order)
    db.commit()

    payment = Payment(razorpay_payment_id="pay_pg_m12_concurrent", order_id=order.id, amount=10000.0, status="FAILED", payment_method="UPI")
    db.add(payment)
    db.commit()

    case = RecoveryCase(
        case_type="payment_failure",
        customer_id=cust.id,
        order_id=order.id,
        payment_id=payment.id,
        amount_at_risk=10000.0,
        status="RECOVERED",
    )
    db.add(case)
    db.commit()

    outcome = Outcome(
        case_id=case.id,
        intervention="RETRY",
        payment_success=True,
        is_recovered=True,
        gross_recovered=10000.0,
        refund_amount=0.0,
        refund_deductions=0.0,
        gateway_cost=100.0,
        communication_cost=10.0,
        discount_given=0.0,
        net_recovered=9890.0,
        attribution_status="DIRECT",
    )
    db.add(outcome)
    db.commit()
    payment_id = payment.id
    db.close()

    refund_id = "rfnd_pg_concurrent_999"
    refund_amount = 2500.0

    # Step 2: Multi-threaded worker task submitting identical refund ID simultaneously
    def worker_task(thread_id):
        worker_db = PGSession()
        res = AttributionEngine.process_refund_deduction(
            db=worker_db,
            razorpay_refund_id=refund_id,
            payment_id=payment_id,
            refund_amount=refund_amount,
        )
        worker_db.close()
        return res

    # Step 3: Launch 5 worker threads simultaneously
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(worker_task, i) for i in range(5)]
        results = [f.result() for f in futures]

    # Step 4: Verify PostgreSQL Results
    success_results = [r for r in results if r["status"] == "success"]
    duplicate_results = [r for r in results if r["status"] == "duplicate_refund_ignored"]

    assert len(success_results) == 1, f"Expected exactly 1 successful execution, got {len(success_results)}"
    assert len(duplicate_results) == 4, f"Expected exactly 4 ignored duplicates, got {len(duplicate_results)}"

    check_db = PGSession()

    # Verify EXACTLY 1 RefundEvent row created in PostgreSQL
    refund_events_count = check_db.query(RefundEvent).filter(
        RefundEvent.razorpay_refund_id == refund_id
    ).count()
    assert refund_events_count == 1

    # Verify Outcome.refund_deductions updated EXACTLY ONCE (₹2,500.00, NOT ₹12,500.00)
    db_outcome = check_db.query(Outcome).filter(Outcome.case_id == case.id).first()
    assert db_outcome.refund_deductions == 2500.0
    assert db_outcome.net_recovered == 7390.0  # 10000 - 2500 - 100 - 10 = 7390

    # Clean up database
    Base.metadata.drop_all(bind=pg_engine)
    check_db.close()
    pg_engine.dispose()
