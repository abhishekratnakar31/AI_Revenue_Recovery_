"""
Factory module for instantiating LLM Providers in RecoverAI.
Supports 'mock', 'gemini', and 'openai'. Unsupported names raise ValueError.
"""

from backend.app.llm.base import LLMProvider
from backend.app.llm.mock_llm_provider import MockLLMProvider
from backend.app.llm.gemini_provider import GeminiLLMProvider
from backend.app.llm.openai_provider import OpenAILLMProvider


def get_llm_provider(provider_name: str = "mock", **kwargs) -> LLMProvider:
    """
    Factory function returning the specified LLMProvider instance.
    Supported provider names: "mock", "gemini", "openai".
    Raises ValueError for unsupported provider names (e.g. "claude").
    """
    name = (provider_name or "mock").lower()
    if name == "mock":
        return MockLLMProvider()
    elif name == "gemini":
        return GeminiLLMProvider(**kwargs)
    elif name == "openai":
        return OpenAILLMProvider(**kwargs)
    else:
        raise ValueError(
            f"Unsupported LLM provider '{provider_name}'. Supported providers are: 'mock', 'gemini', 'openai'."
        )
