"""
Google Gemini LLM Provider implementation using REST API or SDK with structured JSON output.
"""

import os
import json
import logging
from typing import Dict, Any
import urllib.request
import urllib.error

from backend.app.llm.base import LLMProvider
from backend.app.llm.schemas import CommunicationCopySchema, DiagnosticSummarySchema
from backend.app.llm.mock_llm_provider import MockLLMProvider

logger = logging.getLogger("recoverai.llm.gemini")


class GeminiLLMProvider(LLMProvider):
    """
    Concrete LLM provider interfacing with Google Gemini API.
    Uses structured output prompting and Pydantic validation.
    Falls back gracefully to MockLLMProvider on network or API failures.
    """

    def __init__(self, api_key: str = None, model_name: str = "gemini-1.5-flash"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model_name
        self._fallback_provider = MockLLMProvider()

    def generate_customer_communication(
        self,
        case_context: Dict[str, Any],
        action_context: Dict[str, Any],
        channel: str,
    ) -> CommunicationCopySchema:
        if not self.api_key:
            logger.info("GEMINI_API_KEY not set. Falling back to MockLLMProvider.")
            return self._fallback_provider.generate_customer_communication(
                case_context, action_context, channel
            )

        prompt = f"""
You are Customer Communication Assistant for an e-commerce payment recovery system.
Generate communication copy for channel '{channel}'.

CRITICAL INSTRUCTIONS:
- You MUST NOT select or change payment amounts or discounts.
- You MUST NOT manufacture payment URLs or links.
- Respond STRICTLY with a valid JSON object with keys: "channel", "headline", "body", "cta_text".

Context:
Customer First Name: {case_context.get('first_name', 'Customer')}
Order Amount: {case_context.get('currency', 'INR')} {case_context.get('amount', '0.00')}
Failure Reason: {case_context.get('failure_reason', 'Payment failed')}
Discount Percent: {action_context.get('discount_pct', 0)}%
"""
        try:
            res_json = self._call_gemini_api(prompt)
            return CommunicationCopySchema(
                channel=res_json.get("channel", channel.upper()),
                headline=res_json.get("headline", "Payment Update"),
                body=res_json.get("body", "Please click below to complete your payment."),
                cta_text=res_json.get("cta_text", "Pay Now"),
                raw_response={"provider": "gemini", "model": self.model_name},
            )
        except Exception as e:
            logger.warning(f"Gemini API call failed ({e}). Falling back to MockLLMProvider.")
            return self._fallback_provider.generate_customer_communication(
                case_context, action_context, channel
            )

    def generate_merchant_diagnosis(
        self,
        case_context: Dict[str, Any],
        decision_context: Dict[str, Any],
    ) -> DiagnosticSummarySchema:
        if not self.api_key:
            logger.info("GEMINI_API_KEY not set. Falling back to MockLLMProvider.")
            return self._fallback_provider.generate_merchant_diagnosis(
                case_context, decision_context
            )

        prompt = f"""
You are Merchant Diagnostic Specialist for RecoverAI.
Explain payment failure and recovery decision.

CRITICAL INSTRUCTIONS:
- Explain root cause without making unverified assertions.
- Respond STRICTLY with a valid JSON object with keys: "root_cause_analysis", "recommended_next_steps", "confidence_explanation", "merchant_notes".

Context:
Failure Reason: {case_context.get('failure_reason', 'UNKNOWN_ERROR')}
Selected Action: {decision_context.get('selected_action', 'NO_ACTION')}
Expected Net Value: ₹{decision_context.get('expected_net_value', 0.0):.2f}
"""
        try:
            res_json = self._call_gemini_api(prompt)
            return DiagnosticSummarySchema(
                root_cause_analysis=res_json.get("root_cause_analysis", "Technical transaction failure."),
                recommended_next_steps=res_json.get("recommended_next_steps", "Dispatch recovery link."),
                confidence_explanation=res_json.get("confidence_explanation", "High confidence based on ML model."),
                merchant_notes=res_json.get("merchant_notes", "Automated recovery active."),
                raw_response={"provider": "gemini", "model": self.model_name},
            )
        except Exception as e:
            logger.warning(f"Gemini API call failed ({e}). Falling back to MockLLMProvider.")
            return self._fallback_provider.generate_merchant_diagnosis(
                case_context, decision_context
            )

    def _call_gemini_api(self, prompt: str) -> Dict[str, Any]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"response_mime_type": "application/json"},
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            res_body = json.loads(response.read().decode("utf-8"))
            raw_text = res_body["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(raw_text)
