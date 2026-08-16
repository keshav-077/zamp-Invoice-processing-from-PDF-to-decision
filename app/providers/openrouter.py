"""
InvoiceFlow AI — OpenRouter Provider Adapter

Uses the OpenRouter REST API (OpenAI-compatible) for vision-language model inference.
Images are sent as base64-encoded data URLs via requests library.
"""

import base64
import json
import logging
import requests as req

from app.providers.base import LLMProvider, ProviderError
from app.config import settings

logger = logging.getLogger(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider(LLMProvider):
    """OpenRouter API adapter for vision-language model calls."""

    provider_name = "openrouter"

    def __init__(self):
        if not settings.openrouter_api_key:
            raise ProviderError("openrouter", "OPENROUTER_API_KEY not configured")
        self.api_key = settings.openrouter_api_key
        self.model = settings.openrouter_model
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://invoiceflow-ai.local",
            "X-Title": "InvoiceFlow AI",
        }
        logger.info(f"OpenRouter provider initialized with model: {self.model}")

    def _build_image_content(self, images: list[bytes]) -> list[dict]:
        """Convert image bytes to OpenAI-compatible image_url content blocks."""
        content = []
        for img_bytes in images:
            b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{b64}",
                },
            })
        return content

    def _call_api(self, messages: list[dict]) -> str:
        """Make a synchronous HTTP call to the OpenRouter API."""
        payload = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "max_tokens": 8192,
        }

        try:
            response = req.post(
                OPENROUTER_API_URL,
                headers=self.headers,
                data=json.dumps(payload),
                timeout=settings.llm_request_timeout_seconds,
            )

            if response.status_code != 200:
                error_msg = f"HTTP {response.status_code}: {response.text[:500]}"
                raise ProviderError("openrouter", error_msg, retryable=response.status_code >= 500)

            data = response.json()
            text = data.get("choices", [{}])[0].get("message", {}).get("content", "")

            if not text:
                raise ProviderError("openrouter", "Empty response from OpenRouter", retryable=True)

            return text

        except ProviderError:
            raise
        except req.exceptions.Timeout:
            raise ProviderError("openrouter", "Request timed out", retryable=True)
        except Exception as e:
            raise ProviderError("openrouter", str(e), retryable=True) from e

    async def extract_invoice(
        self,
        images: list[bytes],
        prompt: str,
    ) -> str:
        """Run LLM Call #1 — Primary Extraction via OpenRouter."""
        try:
            image_content = self._build_image_content(images)
            image_content.append({"type": "text", "text": prompt})

            messages = [{"role": "user", "content": image_content}]
            text = self._call_api(messages)
            logger.info(f"OpenRouter extraction completed ({len(text)} chars)")
            return text

        except ProviderError:
            raise
        except Exception as e:
            logger.error(f"OpenRouter extraction failed: {e}")
            raise ProviderError("openrouter", str(e), retryable=True) from e

    async def verify_invoice(
        self,
        images: list[bytes],
        extraction_json: str,
        prompt: str,
    ) -> str:
        """Run LLM Call #2 — Independent Verification via OpenRouter."""
        try:
            image_content = self._build_image_content(images)
            full_prompt = f"{prompt}\n\n--- EXTRACTION JSON TO VERIFY ---\n{extraction_json}"
            image_content.append({"type": "text", "text": full_prompt})

            messages = [{"role": "user", "content": image_content}]
            text = self._call_api(messages)
            logger.info(f"OpenRouter verification completed ({len(text)} chars)")
            return text

        except ProviderError:
            raise
        except Exception as e:
            logger.error(f"OpenRouter verification failed: {e}")
            raise ProviderError("openrouter", str(e), retryable=True) from e

    async def classify_pages(
        self,
        images: list[bytes],
        prompt: str,
    ) -> str:
        """Classify pages of a multi-page document via OpenRouter."""
        try:
            image_content = self._build_image_content(images)
            image_content.append({"type": "text", "text": prompt})

            messages = [{"role": "user", "content": image_content}]
            text = self._call_api(messages)
            logger.info(f"OpenRouter page classification completed ({len(text)} chars)")
            return text

        except ProviderError:
            raise
        except Exception as e:
            logger.error(f"OpenRouter page classification failed: {e}")
            raise ProviderError("openrouter", str(e), retryable=True) from e
