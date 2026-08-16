"""
InvoiceFlow AI — Google Gemini Provider Adapter

Uses the google-genai SDK for vision-language model inference.
Supports structured JSON output via response_mime_type.

On overload (503/429) fails fast so the pipeline can fall back to Groq/OpenRouter.
Only tries an alternate Gemini model on 404 (deprecated model ID).
"""

import logging
from google import genai
from google.genai import types

from app.providers.base import LLMProvider, ProviderError
from app.providers.resilience import is_overload_error, run_sync_with_timeout
from app.config import settings

logger = logging.getLogger(__name__)

# Single backup when configured model returns 404 — avoid cycling many dead IDs.
GEMINI_404_FALLBACK = "gemini-2.5-flash"


class GeminiProvider(LLMProvider):
    """Google Gemini API adapter for vision-language model calls."""

    provider_name = "gemini"

    def __init__(self):
        if not settings.gemini_api_key:
            raise ProviderError("gemini", "GEMINI_API_KEY not configured")
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model = settings.gemini_model
        logger.info(f"Gemini provider initialized with model: {self.model}")

    def _build_image_parts(self, images: list[bytes]) -> list:
        """Convert image bytes to Gemini content parts."""
        parts = []
        for img_bytes in images:
            parts.append(
                types.Part.from_bytes(
                    data=img_bytes,
                    mime_type="image/png",
                )
            )
        return parts

    def _call_model(self, model: str, contents: list) -> str:
        """Single generate_content call with timeout."""
        def _request() -> str:
            response = self.client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
            if response.text:
                return response.text
            raise ProviderError(
                "gemini",
                f"Empty response from Gemini model {model}",
                retryable=True,
            )

        return run_sync_with_timeout(_request)

    def _generate_json(self, contents: list) -> str:
        """
        Generate JSON via Gemini.

        - Overload (503/429): fail immediately → cross-provider fallback
        - 404 on primary: one alternate Gemini model, then fail
        """
        models_to_try = [self.model]
        if GEMINI_404_FALLBACK != self.model:
            models_to_try.append(GEMINI_404_FALLBACK)

        last_error: Exception | None = None
        saw_404_only = False

        for model in models_to_try:
            try:
                text = self._call_model(model, contents)
                if model != self.model:
                    logger.info(f"Gemini alternate model succeeded: {model}")
                return text
            except ProviderError:
                raise
            except Exception as e:
                last_error = e
                err = str(e)
                if is_overload_error(e):
                    logger.warning(
                        f"Gemini overloaded ({model}) — skipping remaining Gemini models: "
                        f"{err[:120]}"
                    )
                    raise ProviderError(
                        "gemini",
                        f"Gemini unavailable: {err[:200]}",
                        retryable=True,
                    ) from e
                if "404" in err or "NOT_FOUND" in err:
                    saw_404_only = True
                    logger.warning(f"Gemini model not found ({model}): {err[:120]}")
                    continue
                raise ProviderError("gemini", str(e), retryable=True) from e

        if saw_404_only and last_error:
            raise ProviderError(
                "gemini",
                f"Gemini model unavailable: {last_error}",
                retryable=True,
            ) from last_error
        raise ProviderError("gemini", "Gemini request failed", retryable=True)

    async def extract_invoice(
        self,
        images: list[bytes],
        prompt: str,
    ) -> str:
        """Run LLM Call #1 — Primary Extraction via Gemini."""
        try:
            image_parts = self._build_image_parts(images)
            contents = image_parts + [types.Part.from_text(text=prompt)]
            text = self._generate_json(contents)
            logger.info(f"Gemini extraction completed ({len(text)} chars)")
            return text
        except ProviderError:
            raise
        except Exception as e:
            logger.error(f"Gemini extraction failed: {e}")
            raise ProviderError("gemini", str(e), retryable=True) from e

    async def verify_invoice(
        self,
        images: list[bytes],
        extraction_json: str,
        prompt: str,
    ) -> str:
        """Run LLM Call #2 — Independent Verification via Gemini."""
        try:
            image_parts = self._build_image_parts(images)
            full_prompt = f"{prompt}\n\n--- EXTRACTION JSON TO VERIFY ---\n{extraction_json}"
            contents = image_parts + [types.Part.from_text(text=full_prompt)]
            text = self._generate_json(contents)
            logger.info(f"Gemini verification completed ({len(text)} chars)")
            return text
        except ProviderError:
            raise
        except Exception as e:
            logger.error(f"Gemini verification failed: {e}")
            raise ProviderError("gemini", str(e), retryable=True) from e

    async def classify_pages(
        self,
        images: list[bytes],
        prompt: str,
    ) -> str:
        """Classify pages of a multi-page document via Gemini."""
        try:
            image_parts = self._build_image_parts(images)
            contents = image_parts + [types.Part.from_text(text=prompt)]
            text = self._generate_json(contents)
            logger.info(f"Gemini page classification completed ({len(text)} chars)")
            return text
        except ProviderError:
            raise
        except Exception as e:
            logger.error(f"Gemini page classification failed: {e}")
            raise ProviderError("gemini", str(e), retryable=True) from e
