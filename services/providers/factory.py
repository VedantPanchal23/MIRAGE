"""Factory and registry for LLM Provider Adapters in MIRAGE 3.0.

Enforces strict fail-closed configuration validation, SSRF endpoint protection,
and disallows unconfigured mock fallbacks in production environments.
"""

from services.providers.anthropic_adapter import AnthropicProviderAdapter
from services.providers.base import BaseProviderAdapter
from services.providers.gemini_adapter import GeminiProviderAdapter
from services.providers.groq_adapter import GroqProviderAdapter
from services.providers.mock_adapter import MockProviderAdapter
from services.providers.ollama_adapter import OllamaProviderAdapter
from services.providers.openai_adapter import OpenAIProviderAdapter
from services.providers.ssrf_validator import SSRFValidationError, validate_safe_provider_url
from shared.config import get_settings
from shared.config.settings import EnvironmentType

_OVERRIDES: dict[str, BaseProviderAdapter] = {}


class ProviderConfigurationError(Exception):
    """Raised when provider configuration or destination validation fails."""

    pass


def validate_provider_base_url(url: str, allow_local: bool = False, resolve_dns: bool = True) -> str:
    """Validate provider base URL against approved destination policies and SSRF vectors."""
    try:
        return validate_safe_provider_url(url, allow_local=allow_local, resolve_dns=resolve_dns)
    except SSRFValidationError as err:
        raise ProviderConfigurationError(str(err)) from err


def register_adapter_override(provider_name: str, adapter: BaseProviderAdapter) -> None:
    """Register an adapter override (for deterministic offline unit testing)."""
    _OVERRIDES[provider_name.lower().strip()] = adapter


def clear_adapter_overrides() -> None:
    """Clear all test adapter overrides."""
    _OVERRIDES.clear()


def get_provider_adapter(provider_name: str) -> BaseProviderAdapter:
    """Resolve the authoritative provider adapter instance.

    Strictly fails closed with ProviderConfigurationError if the provider is unknown,
    if required credentials are missing, or if mock adapters are attempted in production.
    """
    norm_name = provider_name.lower().strip()
    if norm_name in _OVERRIDES:
        return _OVERRIDES[norm_name]

    settings = get_settings()

    if norm_name == "mock":
        if settings.environment == EnvironmentType.PRODUCTION:
            raise ProviderConfigurationError("Mock provider is strictly prohibited in production mode")
        if not getattr(settings, "allow_mock_providers", True):
            raise ProviderConfigurationError("Mock provider execution is disabled by configuration")
        return MockProviderAdapter()

    elif norm_name == "openai":
        api_key = getattr(settings, "openai_api_key", "").strip()
        base_url = getattr(settings, "openai_base_url", "https://api.openai.com/v1")
        if not api_key:
            if settings.environment in (EnvironmentType.TEST, EnvironmentType.DEVELOPMENT) and getattr(
                settings, "allow_mock_providers", False
            ):
                return MockProviderAdapter()
            raise ProviderConfigurationError("Missing required OPENAI_API_KEY")
        validate_provider_base_url(base_url, allow_local=False)
        return OpenAIProviderAdapter(api_key=api_key, base_url=base_url)

    elif norm_name == "anthropic":
        api_key = getattr(settings, "anthropic_api_key", "").strip()
        base_url = getattr(settings, "anthropic_base_url", "https://api.anthropic.com/v1")
        if not api_key:
            if settings.environment in (EnvironmentType.TEST, EnvironmentType.DEVELOPMENT) and getattr(
                settings, "allow_mock_providers", False
            ):
                return MockProviderAdapter()
            raise ProviderConfigurationError("Missing required ANTHROPIC_API_KEY")
        validate_provider_base_url(base_url, allow_local=False)
        return AnthropicProviderAdapter(api_key=api_key, base_url=base_url)

    elif norm_name == "google":
        api_key = getattr(settings, "gemini_api_key", "").strip()
        base_url = getattr(settings, "gemini_base_url", "https://generativelanguage.googleapis.com/v1beta")
        if not api_key:
            if settings.environment in (EnvironmentType.TEST, EnvironmentType.DEVELOPMENT) and getattr(
                settings, "allow_mock_providers", False
            ):
                return MockProviderAdapter()
            raise ProviderConfigurationError("Missing required GEMINI_API_KEY")
        validate_provider_base_url(base_url, allow_local=False)
        return GeminiProviderAdapter(api_key=api_key, base_url=base_url)

    elif norm_name == "groq":
        api_key = getattr(settings, "groq_api_key", "").strip()
        base_url = getattr(settings, "llm_upstream_url", "https://api.groq.com/openai/v1")
        if not api_key:
            if settings.environment in (EnvironmentType.TEST, EnvironmentType.DEVELOPMENT) and getattr(
                settings, "allow_mock_providers", False
            ):
                return MockProviderAdapter()
            raise ProviderConfigurationError("Missing required GROQ_API_KEY")
        validate_provider_base_url(base_url, allow_local=False)
        return GroqProviderAdapter(api_key=api_key, base_url=base_url)

    elif norm_name == "openrouter":
        api_key = getattr(settings, "openrouter_api_key", "").strip()
        base_url = "https://openrouter.ai/api/v1"
        if not api_key:
            if settings.environment in (EnvironmentType.TEST, EnvironmentType.DEVELOPMENT) and getattr(
                settings, "allow_mock_providers", False
            ):
                return MockProviderAdapter()
            raise ProviderConfigurationError("Missing required OPENROUTER_API_KEY")
        validate_provider_base_url(base_url, allow_local=False)
        return OpenAIProviderAdapter(api_key=api_key, base_url=base_url)

    elif norm_name in ("huggingface", "hf"):
        api_key = getattr(settings, "huggingface_api_key", "").strip()
        base_url = "https://api-inference.huggingface.co/models"
        if not api_key:
            if settings.environment in (EnvironmentType.TEST, EnvironmentType.DEVELOPMENT) and getattr(
                settings, "allow_mock_providers", False
            ):
                return MockProviderAdapter()
            raise ProviderConfigurationError("Missing required HUGGINGFACE_API_KEY")
        validate_provider_base_url(base_url, allow_local=False)
        return OpenAIProviderAdapter(api_key=api_key, base_url=base_url)

    elif norm_name == "ollama":
        base_url = getattr(settings, "ollama_base_url", "http://localhost:11434")
        validate_provider_base_url(base_url, allow_local=True)
        return OllamaProviderAdapter(base_url=base_url)

    else:
        raise ProviderConfigurationError(f"Unknown or unsupported provider: '{provider_name}'")
