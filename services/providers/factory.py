"""Factory and registry for LLM Provider Adapters in MIRAGE 3.0."""

from services.providers.anthropic_adapter import AnthropicProviderAdapter
from services.providers.base import BaseProviderAdapter
from services.providers.gemini_adapter import GeminiProviderAdapter
from services.providers.mock_adapter import MockProviderAdapter
from services.providers.ollama_adapter import OllamaProviderAdapter
from services.providers.openai_adapter import OpenAIProviderAdapter
from shared.config import get_settings

_OVERRIDES: dict[str, BaseProviderAdapter] = {}


def register_adapter_override(provider_name: str, adapter: BaseProviderAdapter) -> None:
    """Register an adapter override (e.g. for deterministic testing)."""
    _OVERRIDES[provider_name.lower()] = adapter


def clear_adapter_overrides() -> None:
    """Clear all test adapter overrides."""
    _OVERRIDES.clear()


def get_provider_adapter(provider_name: str) -> BaseProviderAdapter:
    """Get the appropriate provider adapter instance based on name and settings."""
    norm_name = provider_name.lower().strip()
    if norm_name in _OVERRIDES:
        return _OVERRIDES[norm_name]

    settings = get_settings()

    if norm_name == "mock":
        return MockProviderAdapter()
    elif norm_name == "openai":
        api_key = getattr(settings, "openai_api_key", "")
        base_url = getattr(settings, "openai_base_url", "https://api.openai.com/v1")
        # In test/dev without API key, fallback cleanly to mock if unconfigured
        if not api_key:
            return MockProviderAdapter()
        return OpenAIProviderAdapter(api_key=api_key, base_url=base_url)
    elif norm_name == "anthropic":
        api_key = getattr(settings, "anthropic_api_key", "")
        base_url = getattr(settings, "anthropic_base_url", "https://api.anthropic.com/v1")
        if not api_key:
            return MockProviderAdapter()
        return AnthropicProviderAdapter(api_key=api_key, base_url=base_url)
    elif norm_name == "google":
        api_key = getattr(settings, "gemini_api_key", "")
        base_url = getattr(settings, "gemini_base_url", "https://generativelanguage.googleapis.com/v1beta")
        if not api_key:
            return MockProviderAdapter()
        return GeminiProviderAdapter(api_key=api_key, base_url=base_url)
    elif norm_name == "ollama":
        base_url = getattr(settings, "ollama_base_url", "http://localhost:11434")
        return OllamaProviderAdapter(base_url=base_url)
    else:
        # Default fallback: return mock adapter rather than failing silently
        return MockProviderAdapter()
