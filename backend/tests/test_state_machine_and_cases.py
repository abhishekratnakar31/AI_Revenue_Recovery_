import os
import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Set test environment
os.environ["USE_TEST_DB"] = "1"
os.environ["TEST_DATABASE_URL"] = "sqlite:///./test.db"

from backend.app.core.database import Base
from backend.app.models.models import (
    Customer, Order, Payment, PaymentAttempt, RecoveryCase, Outcome, AuditLog
)
from backend.app.state_machine.payment_state import (
    PaymentStateMachine, PaymentStatus, InvalidStateTransitionError
)
from backend.app.recovery.case_manager import (
    process_failed_payment_event,
    process_captured_payment_event,
    verify_pending_cases_buffer,
    utc_now
)

engine = create_engine("sqlite:///./test.db", connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def test_state_machine_valid_transitions():
    assert PaymentStateMachine.can_transition("FAILED", "PENDING_VERIFICATION") is True
    assert PaymentStateMachine.can_transition("PENDING_VERIFICATION", "AUTO_RESOLVED") is True
    assert PaymentStateMachine.can_transition("PENDING_VERIFICATION", "RECOVERY_ELIGIBLE") is True
    assert PaymentStateMachine.can_transition("RECOVERY_ELIGIBLE", "RECOVERY_ACTIVE") is True
    assert PaymentStateMachine.can_transition("RECOVERY_ACTIVE", "RECOVERED") is True

    # Test actual transition
    new_state = PaymentStateMachine.transition("PENDING_VERIFICATION", "RECOVERY_ELIGIBLE")
    assert new_state == "RECOVERY_ELIGIBLE"


def test_state_machine_invalid_transitions():
    assert PaymentStateMachine.can_transition("RECOVERED", "FAILED") is False
    assert PaymentStateMachine.can_transition("AUTO_RESOLVED", "RECOVERY_ACTIVE") is False

    with pytest.raises(InvalidStateTransitionError):
        PaymentStateMachine.transition("RECOVERED", "FAILED")


def test_process_failed_payment_event_creation():
    db = TestingSessionLocal()
    payload = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_failed_301",
                    "order_id": "order_301",
                    "customer_id": "cust_301",
                    "amount": 750000,
                    "currency": "INR",
                    "method": "upi",
                    "error_reason": "bank_timeout",
                    "bank": "HDFC"
                }
            }
        }
    }

    case = process_failed_payment_event(db, payload)
    assert case is not None
    assert case.amount_at_risk == 7500.0
    assert case.status == "PENDING_VERIFICATION"

    # Verify linked models
    assert db.query(Customer).count() == 1
    assert db.query(Order).count() == 1
    assert db.query(Payment).count() == 1
    assert db.query(PaymentAttempt).count() == 1
    assert db.query(AuditLog).count() == 1

    attempt = db.query(PaymentAttempt).first()
    assert attempt.attempt_number == 1
    assert attempt.failure_reason == "bank_timeout"
    assert attempt.bank == "HDFC"

    db.close()


def test_payment_attempt_aggregation():
    db = TestingSessionLocal()
    payload1 = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_agg_01",
                    "order_id": "order_agg_shared",
                    "customer_id": "cust_agg",
                    "amount": 500000,
                    "method": "card",
                    "error_reason": "insufficient_funds"
                }
            }
        }
    }

    payload2 = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_agg_01",
                    "order_id": "order_agg_shared",
                    "customer_id": "cust_agg",
                    "amount": 500000,
                    "method": "card",
                    "error_reason": "authentication_failed"
                }
            }
        }
    }

    case1 = process_failed_payment_event(db, payload1)
    case2 = process_failed_payment_event(db, payload2)

    # Must aggregate under the SAME single RecoveryCase
    assert case1.id == case2.id
    assert db.query(RecoveryCase).count() == 1

    # Should have 2 PaymentAttempts linked to payment
    attempts = db.query(PaymentAttempt).filter_by(payment_id=case1.payment_id).all()
    assert len(attempts) == 2
    assert attempts[0].attempt_number == 1
    assert attempts[1].attempt_number == 2
    assert attempts[1].failure_reason == "authentication_failed"

    db.close()


def test_late_capture_auto_resolution():
    db = TestingSessionLocal()
    failed_payload = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_late_cap_99",
                    "order_id": "order_late_cap_99",
                    "customer_id": "cust_late",
                    "amount": 499900,
                    "method": "netbanking"
                }
            }
        }
    }

    captured_payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_late_cap_99",
                    "order_id": "order_late_cap_99",
                    "amount": 499900
                }
            }
        }
    }

    # 1. Receive payment.failed -> case in PENDING_VERIFICATION
    case = process_failed_payment_event(db, failed_payload)
    assert case.status == "PENDING_VERIFICATION"

    # 2. Receive late payment.captured -> case transitions to AUTO_RESOLVED
    resolved_case = process_captured_payment_event(db, captured_payload)
    assert resolved_case is not None
    assert resolved_case.id == case.id
    assert resolved_case.status == "AUTO_RESOLVED"
    assert resolved_case.closed_at is not None

    # 3. Outcome persisted with NATURAL_RECOVERY attribution
    outcome = db.query(Outcome).filter_by(case_id=case.id).first()
    assert outcome is not None
    assert outcome.payment_success is True
    assert outcome.gross_recovered == 4999.0
    assert outcome.attribution_status == "NATURAL_RECOVERY"

    db.close()


def test_recovery_active_to_recovered():
    db = TestingSessionLocal()
    failed_payload = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_rec_active",
                    "order_id": "order_rec_active",
                    "amount": 250000
                }
            }
        }
    }
    captured_payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_rec_active",
                    "order_id": "order_rec_active",
                    "amount": 250000
                }
            }
        }
    }

    case = process_failed_payment_event(db, failed_payload)
    # Manually transition to RECOVERY_ELIGIBLE -> RECOVERY_ACTIVE
    case.status = "RECOVERY_ELIGIBLE"
    db.commit()
    case.status = "RECOVERY_ACTIVE"
    db.commit()

    # Capture arrives after active recovery
    resolved_case = process_captured_payment_event(db, captured_payload)
    assert resolved_case.status == "RECOVERED"

    outcome = db.query(Outcome).filter_by(case_id=case.id).first()
    assert outcome.attribution_status == "DIRECT"

    db.close()


def test_verification_buffer_expiration():
    db = TestingSessionLocal()
    # Create case with created_at set to 10 minutes ago
    past_time = utc_now() - datetime.timedelta(minutes=10)
    cust = Customer(external_customer_id="cust_buffer_test")
    db.add(cust)
    db.commit()

    case = RecoveryCase(
        case_type="payment_failure",
        customer_id=cust.id,
        amount_at_risk=3000.0,
        status="PENDING_VERIFICATION",
        created_at=past_time
    )
    db.add(case)
    db.commit()

    # Run verification buffer check with max_age_seconds=300 (5 mins)
    transitioned = verify_pending_cases_buffer(db, max_age_seconds=300)
    assert transitioned == 1

    db.refresh(case)
    assert case.status == "RECOVERY_ELIGIBLE"

    audit = db.query(AuditLog).filter_by(case_id=case.id).first()
    assert audit.event == "VERIFICATION_BUFFER_EXPIRED"
    assert audit.new_state == "RECOVERY_ELIGIBLE"

    db.close()
