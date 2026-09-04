"""
Deterministic Mock LLM Provider implementation for offline testing, simulations, and fallbacks.
"""

from typing import Dict, Any
from backend.app.llm.base import LLMProvider
from backend.app.llm.schemas import CommunicationCopySchema, DiagnosticSummarySchema


class MockLLMProvider(LLMProvider):
    """
    Mock LLM provider returning deterministic, high-quality copy and diagnostic summaries
    without external network or API calls.
    """

    def generate_customer_communication(
        self,
        case_context: Dict[str, Any],
        action_context: Dict[str, Any],
        channel: str,
    ) -> CommunicationCopySchema:
        ch_upper = channel.upper()
        first_name = case_context.get("first_name", "Valued Customer")
        amount = case_context.get("amount", "0.00")
        currency = case_context.get("currency", "INR")
        action_name = action_context.get("action_type", "PAYMENT_LINK")
        discount_pct = action_context.get("discount_pct", 0)

        if ch_upper == "SMS":
            headline = "Action Required: Payment Pending"
            if discount_pct > 0:
                body = f"Hi {first_name}, your payment of {currency} {amount} failed. Complete now with a {discount_pct}% discount using your secure payment link."
            else:
                body = f"Hi {first_name}, your payment of {currency} {amount} failed. Please complete your transaction using your secure link."
            cta_text = "Pay Now"

        elif ch_upper == "WHATSAPP":
            headline = "Notice: Payment Retried / Link Ready"
            if discount_pct > 0:
                body = f"Hello {first_name},\n\nWe noticed your payment of {currency} {amount} was unsuccessful. We have applied a exclusive {discount_pct}% discount to help you complete your order smoothly."
            else:
                body = f"Hello {first_name},\n\nWe noticed your recent payment attempt of {currency} {amount} could not be processed. Please click below to complete your payment securely."
            cta_text = "Complete Payment"

        else:  # EMAIL
            headline = f"Payment Update for Order #{case_context.get('order_id', 'N/A')}"
            if discount_pct > 0:
                body = f"Dear {first_name},\n\nYour payment of {currency} {amount} for your order encountered a temporary issue. As a courtesy, we have applied a {discount_pct}% discount for immediate payment."
            else:
                body = f"Dear {first_name},\n\nYour payment attempt of {currency} {amount} was unsuccessful due to a processing issue with your bank. You can complete your order using our secure link."
            cta_text = "Pay Securely Now"

        return CommunicationCopySchema(
            channel=ch_upper,
            headline=headline,
            body=body,
            cta_text=cta_text,
            raw_response={"provider": "mock", "status": "success"},
        )

    def generate_merchant_diagnosis(
        self,
        case_context: Dict[str, Any],
        decision_context: Dict[str, Any],
    ) -> DiagnosticSummarySchema:
        failure_reason = case_context.get("failure_reason", "UNKNOWN_ERROR")
        selected_action = decision_context.get("selected_action", "NO_ACTION")
        env_val = decision_context.get("expected_net_value", 0.0)

        return DiagnosticSummarySchema(
            root_cause_analysis=f"The transaction ended with reason '{failure_reason}'. Historical evidence suggests temporary bank authorization timeouts or insufficient funds.",
            recommended_next_steps=f"Action '{selected_action}' was selected with Incremental ENV of ₹{env_val:.2f}. Recommend dispatching automated payment recovery link.",
            confidence_explanation="High confidence based on ML recovery probability score and historical merchant gateway conversion rates.",
            merchant_notes=f"Case #{case_context.get('case_id', 'N/A')}: Automated recovery initiated via {selected_action}.",
            raw_response={"provider": "mock", "status": "success"},
        )
