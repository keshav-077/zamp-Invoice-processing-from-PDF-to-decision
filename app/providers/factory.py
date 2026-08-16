"""
InvoiceFlow AI — Provider Factory

Instantiates LLM providers based on configuration priority.
Returns the first provider with a valid API key.
Supports fallback chain: Gemini → Groq → OpenRouter.
"""

import logging
from app.config import settings
from app.providers.base import LLMProvider, ProviderError

logger = logging.getLogger(__name__)


def _create_provider(name: str) -> LLMProvider | None:
    """
    Attempt to create a provider by name.
    Returns None if the provider cannot be initialized (e.g., missing API key).
    """
    try:
        if name == "gemini":
            from app.providers.gemini import GeminiProvider
            return GeminiProvider()
        elif name == "groq":
            from app.providers.groq import GroqProvider
            return GroqProvider()
        elif name == "openrouter":
            from app.providers.openrouter import OpenRouterProvider
            return OpenRouterProvider()
        else:
            logger.warning(f"Unknown provider: {name}")
            return None
    except ProviderError as e:
        logger.warning(f"Could not initialize provider '{name}': {e}")
        return None
    except Exception as e:
        logger.warning(f"Unexpected error initializing provider '{name}': {e}")
        return None


def get_provider() -> LLMProvider:
    """
    Get the primary LLM provider based on configuration priority.

    Tries each provider in PROVIDER_PRIORITY order.
    Returns the first successfully initialized provider.

    Raises:
        ProviderError: If no provider could be initialized.
    """
    for name in settings.provider_list:
        provider = _create_provider(name)
        if provider is not None:
            logger.info(f"Primary provider: {provider.provider_name}")
            return provider

    raise ProviderError(
        "factory",
        f"No LLM provider could be initialized. "
        f"Tried: {settings.provider_list}. "
        f"Please configure at least one API key in .env"
    )


def get_fallback_providers(exclude: str | list[str] = "") -> list[LLMProvider]:
    """
    Get fallback LLM providers, excluding the specified provider(s).

    Args:
        exclude: Provider name(s) to skip (usually the primary that just failed).

    Returns:
        Initialized fallback providers in priority order.
    """
    excluded = {exclude} if isinstance(exclude, str) else set(exclude)
    fallbacks: list[LLMProvider] = []

    for name in settings.provider_list:
        if name in excluded:
            continue
        provider = _create_provider(name)
        if provider is not None:
            fallbacks.append(provider)

    if not fallbacks:
        logger.warning("No fallback providers available")

    return fallbacks


def get_fallback_provider(exclude: str = "") -> LLMProvider | None:
    """
    Get the first fallback LLM provider, excluding the specified provider.

    Args:
        exclude: Provider name to skip (usually the primary that just failed).

    Returns:
        A fallback LLMProvider, or None if no fallback is available.
    """
    fallbacks = get_fallback_providers(exclude=exclude)
    if fallbacks:
        logger.info(f"Fallback provider: {fallbacks[0].provider_name}")
    return fallbacks[0] if fallbacks else None


def get_available_providers() -> list[str]:
    """Return list of provider names that can be successfully initialized."""
    available = []
    for name in settings.provider_list:
        provider = _create_provider(name)
        if provider is not None:
            available.append(name)
    return available
