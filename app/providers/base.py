"""
InvoiceFlow AI — Abstract LLM Provider Interface

All LLM providers implement this interface. The pipeline never
touches provider-specific code directly.
"""

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """
    Abstract base class for Vision LLM providers.

    Exposes three operations used by the Stage 1 pipeline:
    1. classify_pages — Page-level document triage
    2. extract_invoice — LLM Call #1 (Primary Extraction)
    3. verify_invoice — LLM Call #2 (Independent Verification)
    """

    provider_name: str = "base"

    @abstractmethod
    async def extract_invoice(
        self,
        images: list[bytes],
        prompt: str,
    ) -> str:
        """
        Send invoice page images + extraction prompt to the vision model.

        Args:
            images: List of page images as PNG bytes.
            prompt: The extraction system prompt with schema instructions.

        Returns:
            Raw JSON string from the model response.

        Raises:
            ProviderError: If the API call fails after internal handling.
        """
        ...

    @abstractmethod
    async def verify_invoice(
        self,
        images: list[bytes],
        extraction_json: str,
        prompt: str,
    ) -> str:
        """
        Send original invoice images + extraction JSON to the verifier model.

        Args:
            images: List of original page images as PNG bytes.
            extraction_json: The JSON string from LLM Call #1.
            prompt: The verification prompt.

        Returns:
            Raw JSON string with verification findings.

        Raises:
            ProviderError: If the API call fails after internal handling.
        """
        ...

    @abstractmethod
    async def classify_pages(
        self,
        images: list[bytes],
        prompt: str,
    ) -> str:
        """
        Classify each page of a multi-page document.

        Args:
            images: List of all page images as PNG bytes.
            prompt: The classification prompt.

        Returns:
            Raw JSON string with page classifications.

        Raises:
            ProviderError: If the API call fails after internal handling.
        """
        ...


class ProviderError(Exception):
    """Raised when an LLM provider API call fails."""

    def __init__(self, provider: str, message: str, retryable: bool = False):
        self.provider = provider
        self.retryable = retryable
        super().__init__(f"[{provider}] {message}")
