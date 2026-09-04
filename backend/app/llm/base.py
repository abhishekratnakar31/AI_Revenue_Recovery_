"""
Abstract Base Class for Multi-LLM Provider Abstraction.
Defines the standard interface for LLM providers (Mock, Gemini, OpenAI).
"""

from abc import ABC, abstractmethod
from typing import Dict, Any
from backend.app.llm.schemas import CommunicationCopySchema, DiagnosticSummarySchema


class LLMProvider(ABC):
    """
    Abstract interface for LLM providers in RecoverAI.
    All LLM providers must implement customer copy generation and merchant diagnostic report generation.
    """

    @abstractmethod
    def generate_customer_communication(
        self,
        case_context: Dict[str, Any],
        action_context: Dict[str, Any],
        channel: str,
    ) -> CommunicationCopySchema:
        """
        Generate customer-facing copy for a specific communication channel (SMS, WHATSAPP, EMAIL).
        """
        pass

    @abstractmethod
    def generate_merchant_diagnosis(
        self,
        case_context: Dict[str, Any],
        decision_context: Dict[str, Any],
    ) -> DiagnosticSummarySchema:
        """
        Generate merchant-facing diagnostic summary explaining failure root causes and recovery decisions.
        """
        pass
