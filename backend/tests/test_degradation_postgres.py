"""
Dedicated PostgreSQL Concurrency & Degradation State Transition Test Suite for Milestone 11.

Verifies 5-thread concurrent worker evaluation safety under native PostgreSQL database transactions,
UNIQUE(gateway, payment_method, bank) constraint locking, and state transition isolation semantics.
"""

import os
import time
import pytest
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.core.config import settings
from backend.app.models.models import GatewayRouteStatus, PaymentAttempt, AuditLog
from backend.app.analytics.degradation import GatewayDegradationDetector, utc_now


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


def test_postgres_5_thread_concurrent_degradation_evaluation():
    """
    Test 5 concurrent worker threads evaluating route status for the same route simultaneously against PostgreSQL.
    Verifies that native PostgreSQL UNIQUE(gateway, payment_method, bank) constraint and row-level locking
    result in EXACTLY 1 GatewayRouteStatus row and no duplicate identical transition events.
    """
    pg_engine = create_engine(PG_URL, pool_pre_ping=True)
    Base.metadata.drop_all(bind=pg_engine)
    Base.metadata.create_all(bind=pg_engine)
    PGSession = sessionmaker(autocommit=False, autoflush=False, bind=pg_engine)

    db = PGSession()

    # Step 1: Pre-populate PostgreSQL with 25 failed payment attempts for route ("razorpay", "UPI", "HDFC")
    now = utc_now()
    for i in range(25):
        att = PaymentAttempt(
            payment_id=1,
            attempt_number=i + 1,
            status="failed",
            gateway="razorpay",
            payment_method="UPI",
            bank="HDFC",
            timestamp=now,
        )
        db.add(att)
    db.commit()
    db.close()

    # Step 2: Multi-threaded worker task evaluating the route status simultaneously
    def worker_task(thread_id):
        worker_db = PGSession()
        detector = GatewayDegradationDetector()
        status_rec = detector.evaluate_route_status(worker_db, "razorpay", "UPI", "HDFC")
        worker_db.close()
        return status_rec.status

    # Step 3: Launch 5 worker threads simultaneously
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(worker_task, i) for i in range(5)]
        results = [f.result() for f in futures]

    # Step 4: Verify PostgreSQL Results
    # All 5 threads must return state "CONFIRMED"
    assert all(st == "CONFIRMED" for st in results)

    check_db = PGSession()
    # Verify EXACTLY 1 GatewayRouteStatus row created in PostgreSQL
    routes_count = check_db.query(GatewayRouteStatus).filter(
        GatewayRouteStatus.gateway == "razorpay",
        GatewayRouteStatus.payment_method == "UPI",
        GatewayRouteStatus.bank == "HDFC",
    ).count()
    assert routes_count == 1

    # Verify no duplicate identical transition events occurred (AuditLog contains max 1 transition event)
    audit_count = check_db.query(AuditLog).filter(
        AuditLog.event == "GATEWAY_ROUTE_STATE_CHANGED",
        AuditLog.new_state == "CONFIRMED",
    ).count()
    assert audit_count == 1

    # Clean up database
    Base.metadata.drop_all(bind=pg_engine)
    check_db.close()
    pg_engine.dispose()
