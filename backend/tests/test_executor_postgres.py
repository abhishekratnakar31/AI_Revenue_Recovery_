"""Dedicated PostgreSQL Concurrency & Idempotency Test Suite for RecoverAI Milestone 9.

Verifies 5-thread concurrent worker execution safety under native PostgreSQL database transaction,
unique constraint locking, and side-effect isolation semantics.
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
)
from backend.app.providers.mock_provider import MockPaymentProvider
from backend.app.recovery.executor import ActionExecutor


# Check if PostgreSQL database is reachable
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


def test_postgres_5_thread_concurrent_side_effect_idempotency():
    """Test 5 concurrent worker threads executing the same AgentDecision against real PostgreSQL.
    
    Verifies that native PostgreSQL UNIQUE(idempotency_key) constraint triggers IntegrityError on 4 workers,
    resulting in EXACTLY 1 RecoveryAction row in PostgreSQL AND EXACTLY 1 provider API call.
    """
    pg_engine = create_engine(PG_URL, pool_pre_ping=True)
    Base.metadata.drop_all(bind=pg_engine)
    Base.metadata.create_all(bind=pg_engine)
    PGSession = sessionmaker(autocommit=False, autoflush=False, bind=pg_engine)

    db = PGSession()

    # Step 1: Create test fixtures in PostgreSQL
    ts = time.time_ns()
    customer = Customer(
        external_customer_id=f"cust_pg_{ts}",
        lifetime_value=25000.0,
        preferred_channel="email",
    )
    db.add(customer)
    db.commit()

    order = Order(
        razorpay_order_id=f"ord_pg_{ts}",
        customer_id=customer.id,
        amount=12000.0,
        currency="INR",
        status="failed",
    )
    db.add(order)
    db.commit()

    payment = Payment(
        razorpay_payment_id=f"pay_pg_{ts}",
        order_id=order.id,
        amount=12000.0,
        status="failed",
        payment_method="card",
    )
    db.add(payment)
    db.commit()

    case = RecoveryCase(
        case_type="payment_failure",
        customer_id=customer.id,
        order_id=order.id,
        payment_id=payment.id,
        amount_at_risk=12000.0,
        status="RECOVERY_ELIGIBLE",
    )
    db.add(case)
    db.commit()

    decision = AgentDecision(
        recovery_case_id=case.id,
        selected_action="DISCOUNTED_PAYMENT_LINK_5",
        diagnosis_summary="High-value customer PostgreSQL concurrency test",
        confidence=0.93,
        provider="env_engine",
        model_name=f"PG_Test_Model_{ts}",
        model_version="v1",
        reasoning="Optimal action for PG concurrency verification",
    )
    db.add(decision)
    db.commit()

    case_id = case.id
    decision_id = decision.id
    db.close()

    mock_prov = MockPaymentProvider()

    # Step 2: Define multi-threaded worker task
    def worker_task(thread_id):
        worker_db = PGSession()
        w_dec = worker_db.query(AgentDecision).filter(AgentDecision.id == decision_id).first()
        w_executor = ActionExecutor(provider=mock_prov)
        res_action, res_resp = w_executor.execute_decision(worker_db, case_id, w_dec)
        worker_db.close()
        return res_action.id

    # Step 3: Launch 5 worker threads simultaneously
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(worker_task, i) for i in range(5)]
        results = [f.result() for f in futures]

    # Step 4: Verify PostgreSQL Database Results
    # All 5 threads must return the identical canonical action ID
    assert len(set(results)) == 1

    check_db = PGSession()
    # Verify EXACTLY 1 RecoveryAction row created in PostgreSQL
    db_actions_count = (
        check_db.query(RecoveryAction)
        .filter(RecoveryAction.recovery_case_id == case_id)
        .count()
    )
    assert db_actions_count == 1

    # Verify EXACTLY 1 external provider API call occurred
    assert mock_prov.payment_link_call_count == 1
    assert mock_prov.retry_call_count == 0

    # Clean up test database
    Base.metadata.drop_all(bind=pg_engine)
    check_db.close()
    pg_engine.dispose()
