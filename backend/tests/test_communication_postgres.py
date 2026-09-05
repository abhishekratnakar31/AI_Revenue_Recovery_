"""
Dedicated PostgreSQL Concurrency & Notification Idempotency Test Suite for Milestone 10.

Verifies 5-thread concurrent worker communication safety under native PostgreSQL database transactions,
UNIQUE(idempotency_key) constraint locking on notification_events, and message dispatch isolation semantics.
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
    RecoveryCase,
    AgentDecision,
    RecoveryAction,
    NotificationEvent,
)
from backend.app.communication.customer_agent import CustomerCommunicationAgent


PG_URL = os.getenv("PG_DATABASE_URL", settings.DATABASE_URL)


def is_postgres_available() -> bool:
    if "sqlite" in str(PG_URL).lower():
        return False
    try:
        eng = create_engine(PG_URL, connect_args={"connect_timeout": 3})
        if eng.dialect.name != "postgresql":
            return False
        with eng.connect() as conn:
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not is_postgres_available(),
    reason="PostgreSQL database is not reachable at PG_DATABASE_URL or settings.DATABASE_URL",
)


def test_postgres_5_thread_concurrent_notification_idempotency():
    """
    Test 5 concurrent worker threads attempting to dispatch communication for the same case, action, and channel against PostgreSQL.
    Verifies that native PostgreSQL UNIQUE(idempotency_key) on notification_events results in EXACTLY 1 NotificationEvent row.
    """
    pg_engine = create_engine(PG_URL, pool_pre_ping=True)
    Base.metadata.drop_all(bind=pg_engine)
    Base.metadata.create_all(bind=pg_engine)
    PGSession = sessionmaker(autocommit=False, autoflush=False, bind=pg_engine)

    db = PGSession()

    ts = time.time_ns()
    customer = Customer(
        external_customer_id=f"cust_pg_comm_{ts}",
        first_name="Rahul",
        last_name="Sharma",
        email="rahul.pg@example.com",
        phone="+919876543210",
        opt_out=False,
    )
    db.add(customer)
    db.commit()

    order = Order(
        razorpay_order_id=f"ord_pg_comm_{ts}",
        customer_id=customer.id,
        amount=15000.0,
        currency="INR",
        status="PENDING",
    )
    db.add(order)
    db.commit()

    payment = Payment(
        razorpay_payment_id=f"pay_pg_comm_{ts}",
        order_id=order.id,
        amount=15000.0,
        currency="INR",
        status="FAILED",
    )
    db.add(payment)
    db.commit()

    case = RecoveryCase(
        case_type="payment_failure",
        customer_id=customer.id,
        order_id=order.id,
        payment_id=payment.id,
        amount_at_risk=15000.0,
        status="RECOVERY_ACTIVE",
    )
    db.add(case)
    db.commit()

    action = RecoveryAction(
        recovery_case_id=case.id,
        action_type="DISCOUNTED_PAYMENT_LINK_5",
        idempotency_key=f"action_case_{case.id}_dec_1_DISCOUNTED_PAYMENT_LINK_5",
        status="EXECUTED",
        provider="razorpay",
        action_metadata={
            "provider_link_id": f"plink_pg_{ts}",
            "short_url": "https://rzp.io/i/pg123",
            "original_amount": 15000.0,
            "discount_pct": 5,
            "net_amount": 14250.0,
        },
    )
    db.add(action)
    db.commit()

    case_id = case.id
    action_id = action.id
    db.close()

    # Step 2: Define multi-threaded worker task
    def worker_task(thread_id):
        worker_db = PGSession()
        agent = CustomerCommunicationAgent(worker_db, provider_name="mock")
        notif = agent.process_and_dispatch(case_id, action_id, channel="WHATSAPP")
        worker_db.close()
        return notif.id

    # Step 3: Launch 5 worker threads simultaneously
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(worker_task, i) for i in range(5)]
        results = [f.result() for f in futures]

    # Step 4: Verify PostgreSQL Database Results
    # All 5 threads must return the exact same NotificationEvent ID
    assert len(set(results)) == 1

    check_db = PGSession()
    # Verify EXACTLY 1 NotificationEvent row created in PostgreSQL
    notif_count = (
        check_db.query(NotificationEvent)
        .filter(NotificationEvent.recovery_case_id == case_id)
        .count()
    )
    assert notif_count == 1

    # Clean up test database
    Base.metadata.drop_all(bind=pg_engine)
    check_db.close()
    pg_engine.dispose()
