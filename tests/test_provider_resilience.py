"""Tests for cross-provider fallback and overload detection."""

from unittest.mock import patch

import pytest

from app.providers.base import ProviderError
from app.providers.resilience import is_overload_error, invoke_with_fallback


class FakeProvider:
    def __init__(self, name: str):
        self.provider_name = name


@pytest.mark.asyncio
@patch("app.providers.resilience.get_fallback_providers")
async def test_invoke_with_fallback_uses_second_provider_on_overload(mock_get):
    primary = FakeProvider("gemini")
    secondary = FakeProvider("groq")
    mock_get.return_value = [secondary]

    async def call(provider):
        if provider.provider_name == "gemini":
            raise ProviderError("gemini", "503 UNAVAILABLE", retryable=True)
        return '{"ok": true}'

    text, used = await invoke_with_fallback(primary, "test", call)
    assert used == "groq"
    assert text == '{"ok": true}'


def test_is_overload_detects_503():
    assert is_overload_error(ProviderError("gemini", "503 UNAVAILABLE", retryable=True))
    assert is_overload_error(Exception("429 rate limit exceeded"))
    assert not is_overload_error(ProviderError("gemini", "invalid json", retryable=False))
