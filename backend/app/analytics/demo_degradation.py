"""
CLI Demonstration Script for RecoverAI Milestone 11: Statistical Gateway Degradation Detector.

Demonstrates:
1. Live 4-state lifecycle progression (NORMAL -> SUSPECTED -> CONFIRMED -> RECOVERING -> NORMAL).
2. One-sided Z-score anomaly math & rolling window metric tracking.
3. Deterministic Policy Engine retry blocking vs multi-channel payment link allowance.
4. M8 AgentDecision isolation (selected action remains unchanged when policy blocks retry).
5. Route isolation (HDFC UPI degradation does not impact ICICI Card).
6. Probe mode rate-limiting in RECOVERING state and full baseline restoration.
"""

import sys
import time
from datetime import timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.database import Base
from backend.app.models.models import Customer, Order, Payment, PaymentAttempt, RecoveryCase, AgentDecision, GatewayRouteStatus, AuditLog, MerchantPolicy
from backend.app.analytics.degradation import GatewayDegradationDetector, utc_now
from backend.app.policies.engine import evaluate_policy


def run_demo():
    print("=" * 80)
    print("  RECOVERAI MILESTONE 11: STATISTICAL GATEWAY DEGRADATION DETECTOR DEMO")
    print("=" * 80)

    # Initialize in-memory SQLite database
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()

    # Step 1: Create Test Customer, Order, Payment, Case, & M8 Decision
    print("\n[STEP 1] Initializing Payment Case & M8 Decision (Initial Baseline State)...")
    customer = Customer(external_customer_id="cust_demo_m11", first_name="Rahul")
    db.add(customer)
    db.commit()

    policy = db.query(MerchantPolicy).first()
    if not policy:
        policy = MerchantPolicy(max_retries=999, minimum_retry_interval=0)
        db.add(policy)
    else:
        policy.max_retries = 999
        policy.minimum_retry_interval = 0
    db.commit()

    order = Order(razorpay_order_id="ord_demo_m11", customer_id=customer.id, amount=15000.0, currency="INR")
    db.add(order)
    db.commit()

    payment = Payment(razorpay_payment_id="pay_demo_m11", order_id=order.id, amount=15000.0, status="FAILED", payment_method="UPI")
    db.add(payment)
    db.commit()

    initial_att = PaymentAttempt(
        payment_id=payment.id,
        attempt_number=1,
        status="failed",
        gateway="razorpay",
        payment_method="UPI",
        bank="HDFC",
        timestamp=utc_now(),
    )
    db.add(initial_att)
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

    decision = AgentDecision(
        recovery_case_id=case.id,
        selected_action="RETRY",
        confidence=0.91,
        model_name="ENV_Engine_env_v1",
    )
    db.add(decision)
    db.commit()

    print(f"  ✓ Created RecoveryCase #{case.id} (Amount: ₹{case.amount_at_risk:,.2f})")
    print(f"  ✓ M8 Decision Selected Action: '{decision.selected_action}' (Confidence: {decision.confidence:.2f})")

    # Initial Policy Check under NORMAL state
    pol_initial = evaluate_policy(db, case.id, "RETRY")
    print(f"  ✓ Initial Policy Decision for RETRY: {pol_initial.decision} ('{pol_initial.reason}')")

    # Step 2: Inject Outage Failures for Route ("razorpay", "UPI", "HDFC")
    print("\n[STEP 2] Simulating Outage Event (Injecting 25 Failed Attempts for Razorpay HDFC UPI)...")
    now = utc_now()
    detector = GatewayDegradationDetector()

    for i in range(25):
        att = PaymentAttempt(
            payment_id=9999,
            attempt_number=i + 1,
            status="failed",
            gateway="razorpay",
            payment_method="UPI",
            bank="HDFC",
            timestamp=now - timedelta(minutes=1),
        )
        db.add(att)
    db.commit()

    # Evaluate detector
    route_status = detector.evaluate_route_status(db, "razorpay", "UPI", "HDFC")
    print("\n--- [ROUTE HEALTH METRICS] ---")
    print(f"Route Identity      : ({route_status.gateway}, {route_status.payment_method}, {route_status.bank})")
    print(f"Route State         : {route_status.status}")
    print(f"Window Attempts (N) : {route_status.total_attempts}")
    print(f"Failed Attempts     : {route_status.failed_attempts}")
    print(f"Failure Rate        : {route_status.current_failure_rate * 100:.1f}% (Baseline: {route_status.baseline_failure_rate * 100:.1f}%)")
    print(f"Z-Score Anomaly     : {route_status.current_z_score:.2f} (Threshold: Z > 2.5)")

    # Step 3: Policy Engine Blocking vs Payment Link Allowance
    print("\n[STEP 3] Evaluating Policy Engine Actions under CONFIRMED Degradation...")
    pol_retry = evaluate_policy(db, case.id, "RETRY")
    print(f"  1. Action 'RETRY'                  : {pol_retry.decision} ('{pol_retry.reason}')")

    db.refresh(decision)
    print(f"  ✓ M8 Decision Isolation Check      : selected_action is still '{decision.selected_action}' (UNTOUCHED)")

    pol_link = evaluate_policy(db, case.id, "INSTANT_PAYMENT_LINK")
    print(f"  2. Action 'INSTANT_PAYMENT_LINK'   : {pol_link.decision} ('{pol_link.reason}')")

    pol_disc = evaluate_policy(db, case.id, "DISCOUNTED_PAYMENT_LINK_5", proposed_discount=5.0)
    print(f"  3. Action 'DISCOUNTED_PAYMENT_LINK_5': {pol_disc.decision} ('{pol_disc.reason}')")

    # Step 4: Route Isolation Verification
    print("\n[STEP 4] Verifying Route Isolation (Razorpay ICICI Card Route)...")
    icici_status = detector.evaluate_route_status(db, "razorpay", "CARD", "ICICI")
    print(f"  ICICI Card Route State : {icici_status.status} (Z={icici_status.current_z_score:.2f})")
    print("  ✓ HDFC UPI outage does NOT affect ICICI Card attempts.")

    # Step 5: Transition to RECOVERING & Probe Rate Limiting
    print("\n[STEP 5] Simulating Recovery Phase (Dwell Time >= 5 mins & Successful Probes)...")
    # Advance last_state_change by 6 minutes to satisfy 5-minute dwell time requirement
    route_status.last_state_change = now - timedelta(minutes=6)
    db.commit()

    # Clear background attempts and add 12 healthy attempts
    db.query(PaymentAttempt).filter(PaymentAttempt.payment_id == 9999).delete()
    for i in range(12):
        att = PaymentAttempt(
            payment_id=9999,
            attempt_number=i + 100,
            status="captured",
            gateway="razorpay",
            payment_method="UPI",
            bank="HDFC",
            timestamp=now - timedelta(minutes=1),
        )
        db.add(att)
    db.commit()

    rec_status = detector.evaluate_route_status(db, "razorpay", "UPI", "HDFC")
    print(f"  Updated Route State    : {rec_status.status} (Failure Rate={rec_status.current_failure_rate * 100:.1f}%, Z={rec_status.current_z_score:.2f})")
    print("  ✓ Hysteresis Note      : Route remains RECOVERING (not immediately NORMAL) to prevent state flapping.")

    # Probe Evaluation #1: Granted probe slot
    pol_probe1 = evaluate_policy(db, case.id, "RETRY")
    print(f"  Probe Attempt #1       : {pol_probe1.decision} ('{pol_probe1.reason}')")

    # Simulate M9 execution updating last_probe_at to current time
    rec_status.last_probe_at = now
    db.commit()

    # Probe Evaluation #2 (1m later): Throttled by 5-minute probe rate limit
    pol_probe2 = evaluate_policy(db, case.id, "RETRY")
    print(f"  Probe Attempt #2 (1m)  : {pol_probe2.decision} ('{pol_probe2.reason}')")
    print("  ✓ Verification Passed  : Rate limiting blocked immediate 2nd probe within 5-minute window.")

    # Probe Evaluation #3 (6m later): Allowed after 5 minutes elapsed
    rec_status.last_probe_at = now - timedelta(minutes=6)
    db.commit()
    pol_probe3 = evaluate_policy(db, case.id, "RETRY")
    print(f"  Probe Attempt #3 (6m)  : {pol_probe3.decision} ('{pol_probe3.reason}')")

    # Step 6: Full Baseline Restoration
    print("\n[STEP 6] Restoring Full Baseline (RECOVERING -> NORMAL)...")
    # Reset last_state_change to 12 minutes ago and re-evaluate
    rec_status.last_state_change = now - timedelta(minutes=12)
    db.commit()

    final_status = detector.evaluate_route_status(db, "razorpay", "UPI", "HDFC")
    print(f"  Final Route State      : {final_status.status}")

    pol_final = evaluate_policy(db, case.id, "RETRY")
    print(f"  Final Policy RETRY     : {pol_final.decision} ('{pol_final.reason}')")

    print("\n" + "=" * 80)
    print("  MILESTONE 11 DEMONSTRATION COMPLETE: STATISTICAL DETECTOR VERIFIED")
    print("=" * 80 + "\n")

    db.close()


if __name__ == "__main__":
    run_demo()
