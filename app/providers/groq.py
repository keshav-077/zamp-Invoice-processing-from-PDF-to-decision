"""
InvoiceFlow AI — Groq Provider Adapter

Uses the Groq SDK (OpenAI-compatible) for vision-language model inference.
Images are sent as base64-encoded data URLs.
"""

import base64
import logging
from groq import Groq

from app.providers.base import LLMProvider, ProviderError
from app.providers.resilience import run_sync_with_timeout
from app.config import settings

logger = logging.getLogger(__name__)


class GroqProvider(LLMProvider):
    """Groq API adapter for vision-language model calls."""

    provider_name = "groq"

    def __init__(self):
        if not settings.groq_api_key:
            raise ProviderError("groq", "GROQ_API_KEY not configured")
        self.client = Groq(api_key=settings.groq_api_key)
        self.model = settings.groq_model
        logger.info(f"Groq provider initialized with model: {self.model}")

    def _build_image_content(self, images: list[bytes]) -> list[dict]:
        """Convert image bytes to OpenAI-compatible image_url content blocks."""
        content = []
        for img_bytes in images:
            b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{b64}",
                },
            })
        return content

    def _chat_with_json_retry(self, image_content: list[dict], prompt: str) -> str:
        """Call Groq chat API, retrying without strict JSON mode if needed."""
        messages = [{
            "role": "user",
            "content": [{"type": "text", "text": prompt}, *image_content],
        }]
        kwargs = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 8192,
            "temperature": 0,
        }

        def _call(strict_json: bool) -> str:
            call_kwargs = dict(kwargs)
            if strict_json:
                call_kwargs["response_format"] = {"type": "json_object"}
            response = self.client.chat.completions.create(**call_kwargs)
            text = response.choices[0].message.content
            if not text:
                raise ProviderError("groq", "Empty response from Groq", retryable=True)
            return text

        def _request() -> str:
            try:
                return _call(strict_json=True)
            except Exception as e:
                if "json_validate_failed" not in str(e):
                    raise
                return _call(strict_json=False)

        return run_sync_with_timeout(_request)

    async def extract_invoice(
        self,
        images: list[bytes],
        prompt: str,
    ) -> str:
        """Run LLM Call #1 — Primary Extraction via Groq."""
        try:
            image_content = self._build_image_content(images)
            text = self._chat_with_json_retry(image_content, prompt)
            logger.info(f"Groq extraction completed ({len(text)} chars)")
            return text

        except ProviderError:
            raise
        except Exception as e:
            logger.error(f"Groq extraction failed: {e}")
            raise ProviderError("groq", str(e), retryable=True) from e

    async def verify_invoice(
        self,
        images: list[bytes],
        extraction_json: str,
        prompt: str,
    ) -> str:
        """Run LLM Call #2 — Independent Verification via Groq."""
        try:
            image_content = self._build_image_content(images)
            full_prompt = f"{prompt}\n\n--- EXTRACTION JSON TO VERIFY ---\n{extraction_json}"
            text = self._chat_with_json_retry(image_content, full_prompt)
            logger.info(f"Groq verification completed ({len(text)} chars)")
            return text

        except ProviderError:
            raise
        except Exception as e:
            logger.error(f"Groq verification failed: {e}")
            raise ProviderError("groq", str(e), retryable=True) from e

    async def classify_pages(
        self,
        images: list[bytes],
        prompt: str,
    ) -> str:
        """Classify pages of a multi-page document via Groq."""
        try:
            image_content = self._build_image_content(images)
            text = self._chat_with_json_retry(image_content, prompt)
            logger.info(f"Groq page classification completed ({len(text)} chars)")
            return text

        except ProviderError:
            raise
        except Exception as e:
            logger.error(f"Groq page classification failed: {e}")
            raise ProviderError("groq", str(e), retryable=True) from e
