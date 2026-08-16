"""
Shared LLM provider resilience: timeouts, overload detection, cross-provider fallback.
"""

from __future__ import annotations

import concurrent.futures
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.config import settings
from app.providers.base import LLMProvider, ProviderError
from app.providers.factory import get_fallback_providers

logger = logging.getLogger(__name__)

T = TypeVar("T")

OVERLOAD_MARKERS = (
    "503",
    "429",
    "UNAVAILABLE",
    "RESOURCE_EXHAUSTED",
    "HIGH DEMAND",
    "OVERLOADED",
    "RATE LIMIT",
    "RATE_LIMIT",
)


def is_overload_error(error: BaseException) -> bool:
    """True when the provider is overloaded/unavailable — switch provider, don't retry same one."""
    if isinstance(error, ProviderError) and error.retryable:
        msg = str(error).upper()
        return any(marker in msg for marker in OVERLOAD_MARKERS)
    msg = str(error).upper()
    return any(marker in msg for marker in OVERLOAD_MARKERS)


def run_sync_with_timeout(func: Callable[[], str], timeout: float | None = None) -> str:
    """Run a blocking LLM call with a wall-clock timeout."""
    limit = timeout if timeout is not None else settings.llm_request_timeout_seconds
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(func)
        try:
            return future.result(timeout=limit)
        except concurrent.futures.TimeoutError as e:
            raise ProviderError(
                "provider",
                f"LLM request timed out after {limit}s",
                retryable=True,
            ) from e


async def invoke_with_fallback(
    primary: LLMProvider,
    operation: str,
    call: Callable[[LLMProvider], Awaitable[T]],
) -> tuple[T, str]:
    """
    Try primary provider, then fall back through configured priority order.

    Returns:
        (response_text, provider_name_used)
    """
    tried = {primary.provider_name}
    providers: list[LLMProvider] = [primary]
    providers.extend(get_fallback_providers(exclude=tried))

    last_error: Exception | None = None
    for provider in providers:
        try:
            logger.info(f"{operation}: trying provider {provider.provider_name}")
            result = await call(provider)
            if provider.provider_name != primary.provider_name:
                logger.info(
                    f"{operation}: succeeded via fallback provider {provider.provider_name}"
                )
            return result, provider.provider_name
        except ProviderError as e:
            last_error = e
            logger.warning(f"{operation}: {provider.provider_name} failed: {e}")
            if is_overload_error(e):
                continue
            if not e.retryable:
                raise
            continue
        except Exception as e:
            last_error = e
            logger.warning(f"{operation}: {provider.provider_name} failed: {e}")
            if is_overload_error(e):
                continue
            raise ProviderError(provider.provider_name, str(e), retryable=True) from e

    if last_error:
        if isinstance(last_error, ProviderError):
            raise last_error
        raise ProviderError("factory", str(last_error), retryable=False)
    raise ProviderError("factory", f"{operation}: all providers failed", retryable=False)
