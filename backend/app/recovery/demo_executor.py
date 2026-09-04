"""CLI Demonstration Script for RecoverAI Milestone 9 Action Executor Engine.

Demonstrates end-to-end execution flow:
Ingesting payment failure -> Calibrated ML Prediction -> Milestone 8 ENV candidate decisioning -> Milestone 9 Idempotent Action Execution & Provider Abstraction.
"""

import os
import sys
import json
import time
from decimal import Decimal

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models.models import Customer, Order, Payment, RecoveryCase, AgentDecision, RecoveryAction, AuditLog
from backend.app.recovery.env_engine import select_optimal_recovery_action
from backend.app.recovery.executor import ActionExecutor
from backend.app.providers import get_payment_provider, MockPaymentProvider, RazorpayPaymentProvider


def run_demo():
    print("================================================================================")
    print("      RecoverAI Milestone 9: Action Executor & Provider Abstraction Engine")
    print("================================================================================")

    # Setup isolated in-memory DB engine for demonstration
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    print("\n[Step 1] Ingesting Payment Failure Event into Relational Engine...")
    customer = Customer(
        external_customer_id="cust_demo_premium_99",
        lifetime_value=24500.0,
        preferred_channel="email",
    )
    db.add(customer)
    db.commit()

    order = Order(
        razorpay_order_id="ord_demo_9001",
        customer_id=customer.id,
        amount=15000.0,
        currency="INR",
        status="failed",
    )
    db.add(order)
    db.commit()

    payment = Payment(
        razorpay_payment_id="pay_demo_9001",
        order_id=order.id,
        amount=15000.0,
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
        amount_at_risk=15000.0,
        status="RECOVERY_ELIGIBLE",
    )
    db.add(case)
    db.commit()
    print(f"  -> Created RecoveryCase ID: {case.id} (Amount at Risk: ₹{case.amount_at_risk:,.2f})")

    print("\n[Step 2] Executing Milestone 8 ENV Optimization Engine...")
    env_result = select_optimal_recovery_action(db, case.id)
    agent_dec = (
        db.query(AgentDecision)
        .filter(AgentDecision.recovery_case_id == case.id)
        .order_by(AgentDecision.id.desc())
        .first()
    )
    print(f"  -> Optimal Action Selected: {agent_dec.selected_action}")
    print(f"  -> Decision Confidence:     {agent_dec.confidence:.4f}")
    print(f"  -> Max Incremental ENV:    +₹{env_result.selected_incremental_env:,.2f}")

    print("\n[Step 3] Executing Milestone 9 Idempotent Action Executor (Mock Provider)...")
    mock_prov = MockPaymentProvider()
    executor = ActionExecutor(provider=mock_prov)
    
    action, resp = executor.execute_decision(db, case.id, agent_dec)
    print(f"  -> Executed Action Key:     {action.idempotency_key}")
    print(f"  -> Execution Status:        {action.status}")
    print(f"  -> Action Outcome:          {action.outcome}")
    print(f"  -> Canonical Provider TxID: {action.provider_transaction_id}")
    print(f"  -> Case State Machine:      {case.status}")
    print(f"  -> Provider Metadata:       {json.dumps(action.action_metadata, indent=2)}")

    print("\n[Step 4] Verifying Side-Effect Idempotency (Re-executing same decision)...")
    dup_action, dup_resp = executor.execute_decision(db, case.id, agent_dec)
    print(f"  -> Re-execution Status:     {dup_action.status}")
    print(f"  -> Provider Call Count:     {mock_prov.payment_link_call_count + mock_prov.retry_call_count} (EXACTLY 1 external API call)")
    print(f"  -> Database Action Rows:    {db.query(RecoveryAction).count()} (EXACTLY 1 DB row)")

    print("\n[Step 5] Demonstrating Live/Staging Razorpay Provider Integration (Scenario 2: DISCOUNTED_PAYMENT_LINK_5)...")
    rzp_prov = RazorpayPaymentProvider(key_id="rzp_test_mock_keys", key_secret="mock_secret")
    rzp_executor = ActionExecutor(provider=rzp_prov)
    
    # Create new decision for Razorpay provider test
    dec_rzp = AgentDecision(
        recovery_case_id=case.id,
        selected_action="DISCOUNTED_PAYMENT_LINK_5",
        confidence=0.91,
        provider="env_engine",
        model_name="ENV_Engine_rzp_demo",
    )
    db.add(dec_rzp)
    db.commit()

    rzp_action, rzp_resp = rzp_executor.execute_decision(db, case.id, dec_rzp)
    print(f"  -> Razorpay Action Status:  {rzp_action.status}")
    print(f"  -> Razorpay Provider:       {rzp_action.provider}")
    print(f"  -> Original Amount:         ₹{Decimal(rzp_action.action_metadata['original_amount']):,.2f}")
    print(f"  -> Merchant Discount:       {rzp_action.action_metadata['discount_pct']}%")
    print(f"  -> Net Payable Amount:      ₹{Decimal(rzp_action.action_metadata['net_amount']):,.2f}")
    print(f"  -> Canonical Short URL:     {rzp_action.action_metadata.get('short_url')}")

    print("\n[Step 6] System Audit Log Verification...")
    audits = db.query(AuditLog).filter(AuditLog.case_id == case.id).all()
    for a in audits:
        print(f"  - Audit [{a.timestamp.strftime('%H:%M:%S')}]: Event={a.event:30s} | Actor={a.actor:15s} | Reason={a.reason}")

    print("\n================================================================================")
    print("      Milestone 9 Action Executor & Provider Abstraction Engine Complete!      ")
    print("================================================================================")
    db.close()


if __name__ == "__main__":
    run_demo()
