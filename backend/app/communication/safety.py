"""
Deterministic Post-LLM Safety Gate & Semantic Validation Engine.
Enforces architectural safety rules:
1. LLM cannot manufacture payment URLs (canonical URL injected by backend from M9 response).
2. Monetary amount & discount verification (semantic validation replaces hallucinated prices with fallback).
3. SMS length constraints (<= 160 chars; exceeding triggers deterministic fallback rather than naive truncation).
4. Structural Email HTML rendering (separates LLM text from HTML branding template).
"""

import re
import logging
from typing import Dict, Any
from backend.app.llm.schemas import CommunicationCopySchema

logger = logging.getLogger("recoverai.communication.safety")


class CommunicationSafetyGate:
    """
    Deterministic safety gate executed on all raw LLM copy outputs prior to customer dispatch.
    """

    @staticmethod
    def validate_and_sanitize(
        copy: CommunicationCopySchema,
        backend_context: Dict[str, Any],
        action_metadata: Dict[str, Any],
        channel: str,
    ) -> CommunicationCopySchema:
        """
        Validates raw LLM copy output against authoritative backend parameters.
        Returns a sanitized, safe CommunicationCopySchema.
        """
        ch_upper = channel.upper()
        canonical_url = action_metadata.get("short_url") or action_metadata.get("payment_url") or ""
        expected_amount = str(backend_context.get("amount", ""))
        expected_discount = str(action_metadata.get("discount_pct", 0))

        headline = copy.headline.strip()
        body = copy.body.strip()
        cta_text = copy.cta_text.strip()
        fallback_triggered = False
        fallback_reason = None

        # Rule 1: Check for hallucinated URLs in LLM body/headline
        url_pattern = r'https?://[^\s]+'
        found_urls = re.findall(url_pattern, body + " " + headline)
        for url in found_urls:
            if url != canonical_url:
                logger.warning(f"LLM hallucinated unauthorized payment URL '{url}'. Stripping URL.")
                body = re.sub(url_pattern, "", body).strip()

        # Rule 2: Semantic Money & Discount Protection
        # Extract currency numbers like ₹13,500 or 13500 from body
        # If body contains a monetary number that contradicts expected net_amount or original_amount, reject copy
        net_amount_val = action_metadata.get("net_amount") or backend_context.get("amount")
        if net_amount_val:
            net_amt_str = f"{float(net_amount_val):.2f}"
            # Check for numbers in body that look like currency amounts but differ from expected net_amount / original_amount
            # e.g., if net_amount is 14250.00 and body contains 13500 or 13,500
            number_matches = re.findall(r'₹?\s*([0-9,]+(?:\.[0-9]{2})?)', body)
            for match in number_matches:
                clean_num = match.replace(",", "")
                try:
                    num_float = float(clean_num)
                    # Ignore 0, 100, or small discount percentages
                    if num_float > 100 and abs(num_float - float(net_amount_val)) > 1.0 and abs(num_float - float(backend_context.get("amount", 0))) > 1.0:
                        fallback_triggered = True
                        fallback_reason = f"Hallucinated monetary amount {num_float} != expected {net_amount_val}"
                        break
                except ValueError:
                    pass

        # Rule 3: SMS 160-Character Length Boundary
        if ch_upper == "SMS" and not fallback_triggered:
            # Append URL length if URL will be appended
            full_sms_len = len(body) + (len(canonical_url) + 1 if canonical_url else 0)
            if full_sms_len > 160:
                fallback_triggered = True
                fallback_reason = f"SMS copy length {full_sms_len} chars exceeds 160 char limit"

        # Apply Deterministic Fallback if Safety Validation Failed
        if fallback_triggered:
            logger.warning(f"Safety Gate Rejected LLM Copy: {fallback_reason}. Applying Deterministic Fallback.")
            first_name = backend_context.get("first_name", "Valued Customer")
            amount = backend_context.get("amount", "0.00")
            currency = backend_context.get("currency", "INR")
            discount_pct = action_metadata.get("discount_pct", 0)

            if ch_upper == "SMS":
                headline = "Payment Notice"
                if discount_pct > 0:
                    body = f"Hi {first_name}, your payment of {currency} {amount} failed. Complete now with a {discount_pct}% discount."
                else:
                    body = f"Hi {first_name}, your payment of {currency} {amount} failed. Please complete your transaction."
                cta_text = "Pay Now"
            elif ch_upper == "WHATSAPP":
                headline = "Payment Notice"
                if discount_pct > 0:
                    body = f"Hello {first_name},\n\nWe noticed your payment of {currency} {amount} was unsuccessful. We have applied a {discount_pct}% discount to help you complete your order."
                else:
                    body = f"Hello {first_name},\n\nWe noticed your recent payment attempt of {currency} {amount} could not be processed. Please click below to complete your payment securely."
                cta_text = "Complete Payment"
            else:
                headline = f"Payment Update for Order #{backend_context.get('order_id', 'N/A')}"
                body = f"Dear {first_name},\n\nYour payment attempt of {currency} {amount} was unsuccessful. Please complete your transaction using our secure payment link."
                cta_text = "Pay Securely Now"

        # Rule 4: Canonical Payment URL Backend Injection
        # Ensure the payment URL is explicitly appended by backend, never left to LLM formatting
        if canonical_url and canonical_url not in body:
            if ch_upper == "SMS":
                body = f"{body}\n{canonical_url}"
            elif ch_upper == "WHATSAPP":
                body = f"{body}\n\nLink: {canonical_url}"
            # For EMAIL, URL will be injected into HTML CTA button by render_email_template

        sanitized_copy = CommunicationCopySchema(
            channel=ch_upper,
            headline=headline,
            body=body,
            cta_text=cta_text,
            raw_response={
                "safety_gate_passed": not fallback_triggered,
                "fallback_reason": fallback_reason,
                "canonical_url_injected": bool(canonical_url),
            },
        )
        return sanitized_copy

    @staticmethod
    def render_email_template(copy: CommunicationCopySchema, canonical_url: str) -> str:
        """
        Wraps sanitized email headline, body, and canonical payment URL inside a responsive HTML template.
        """
        button_html = ""
        if canonical_url:
            button_html = f"""
            <div style="margin: 24px 0;">
                <a href="{canonical_url}" style="background-color: #4F46E5; color: #FFFFFF; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">
                    {copy.cta_text}
                </a>
            </div>
            """

        formatted_body = copy.body.replace("\n", "<br>")

        html_template = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{copy.headline}</title>
</head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #1F2937; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background-color: #F9FAFB; padding: 24px; border-radius: 8px; border: 1px solid #E5E7EB;">
        <h2 style="color: #111827; margin-top: 0;">{copy.headline}</h2>
        <div style="margin-bottom: 16px;">
            {formatted_body}
        </div>
        {button_html}
        <hr style="border: none; border-top: 1px solid #E5E7EB; margin: 24px 0;">
        <p style="font-size: 12px; color: #6B7280; text-align: center;">
            RecoverAI Automated Notification &bull; If you have already paid, please ignore this email.
        </p>
    </div>
</body>
</html>"""
        return html_template
