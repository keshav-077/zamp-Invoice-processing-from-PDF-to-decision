"""
InvoiceFlow AI — Page Classifier

Classifies pages of multi-page documents to prevent semantic contamination.
Only pages classified as 'line_items' are sent to the extraction step.

For single-page documents, classification is skipped (treat as line_items).
"""

import json
import logging
from app.models.page import PageClassification
from app.providers.base import LLMProvider, ProviderError
from app.providers.resilience import invoke_with_fallback

logger = logging.getLogger(__name__)

CLASSIFICATION_PROMPT = """You are a document page classifier for invoice processing.

For each page image provided, classify it into exactly ONE of these categories:
- "line_items": Pages containing invoice header information, invoice details, amounts, or line-item tables. This includes the main invoice page(s).
- "terms_and_conditions": Pages containing legal terms, contractual conditions, or policies.
- "signature_block": Pages primarily containing signatures, stamps, or approval blocks.
- "attachment": Supporting documents, receipts, delivery notes, or supplementary materials.
- "other": Any page that does not fit the above categories (blank pages, cover pages, etc.).

IMPORTANT:
- If a page contains BOTH invoice data AND terms, classify it as "line_items" (invoice data takes priority).
- Provide a confidence score (0.0–1.0) for each classification.
- Return valid JSON only.

Return a JSON object with this exact structure:
{
  "pages": [
    {"page_number": 1, "classification": "line_items", "confidence": 0.95},
    {"page_number": 2, "classification": "terms_and_conditions", "confidence": 0.88}
  ]
}
"""


class PageClassifier:
    """Classifies multi-page document pages for invoice triage."""

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    async def classify(self, page_images: list[bytes]) -> list[PageClassification]:
        """
        Classify pages of a document.

        For single-page documents, skips LLM call and returns line_items.
        For multi-page documents, uses the vision model.

        Args:
            page_images: List of page images as PNG bytes.

        Returns:
            List of PageClassification objects.
        """
        # Single page — skip classification, treat as invoice
        if len(page_images) == 1:
            logger.info("Single page document — skipping classification")
            return [
                PageClassification(
                    page_number=1,
                    classification="line_items",
                    confidence=1.0,
                )
            ]

        # Multi-page — use LLM for classification
        logger.info(f"Classifying {len(page_images)} pages via LLM")
        try:
            async def do_classify(provider: LLMProvider) -> str:
                return await provider.classify_pages(
                    images=page_images,
                    prompt=CLASSIFICATION_PROMPT,
                )

            raw_response, used = await invoke_with_fallback(
                self.provider,
                "page classification",
                do_classify,
            )
            logger.info(f"Page classification completed via provider: {used}")
            return self._parse_classification(raw_response, len(page_images))

        except ProviderError as e:
            logger.warning(f"Page classification failed: {e}. Defaulting all pages to line_items.")
            # Fallback: treat all pages as invoice content
            return [
                PageClassification(
                    page_number=i + 1,
                    classification="line_items",
                    confidence=0.5,
                )
                for i in range(len(page_images))
            ]

    def _parse_classification(
        self, raw_json: str, total_pages: int
    ) -> list[PageClassification]:
        """Parse and validate classification response from LLM."""
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            logger.warning("Classification JSON parse failed — defaulting all to line_items")
            return self._default_classifications(total_pages)

        pages_data = data.get("pages", data) if isinstance(data, dict) else data

        if not isinstance(pages_data, list):
            logger.warning("Unexpected classification format — defaulting all to line_items")
            return self._default_classifications(total_pages)

        classifications = []
        valid_types = {"line_items", "terms_and_conditions", "signature_block", "attachment", "other"}

        for item in pages_data:
            try:
                cls_type = item.get("classification", "line_items")
                if cls_type not in valid_types:
                    cls_type = "line_items"

                classifications.append(
                    PageClassification(
                        page_number=item.get("page_number", len(classifications) + 1),
                        classification=cls_type,
                        confidence=float(item.get("confidence", 0.5)),
                    )
                )
            except (ValueError, TypeError) as e:
                logger.warning(f"Skipping invalid page classification: {e}")
                continue

        # Ensure all pages are covered
        classified_pages = {c.page_number for c in classifications}
        for i in range(1, total_pages + 1):
            if i not in classified_pages:
                classifications.append(
                    PageClassification(
                        page_number=i,
                        classification="line_items",
                        confidence=0.5,
                    )
                )

        classifications.sort(key=lambda c: c.page_number)
        logger.info(
            f"Page classifications: "
            + ", ".join(f"p{c.page_number}={c.classification}" for c in classifications)
        )
        return classifications

    def _default_classifications(self, total_pages: int) -> list[PageClassification]:
        """Fallback: treat all pages as line_items."""
        return [
            PageClassification(
                page_number=i + 1,
                classification="line_items",
                confidence=0.5,
            )
            for i in range(total_pages)
        ]
