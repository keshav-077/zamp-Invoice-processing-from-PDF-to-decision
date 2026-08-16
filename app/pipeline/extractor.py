"""
InvoiceFlow AI — Primary Extraction (LLM Call #1)

Uses a Vision-Language Model to understand invoice documents and extract
structured financial information with field-level confidence and status.

Design principles:
- Never guess missing values (return null with not_found)
- Provide confidence as a routing signal, not a truth label
- Distinguish extracted vs inferred vs not_found vs uncertain
"""

import json
import logging
from app.models.extraction import (
    InvoiceExtraction,
    FieldExtraction,
    LineItem,
    ExtraCharge,
    TypedReference,
    CustomFact,
    TaxComponent,
)
from app.providers.base import LLMProvider, ProviderError

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """You are an expert invoice data extraction system. Analyze the provided invoice document image(s) and extract structured financial information.

## EXTRACTION RULES

1. **Extract these fields** from the invoice:
   - vendor_name: The company/entity that issued the invoice
   - invoice_number: The unique invoice identifier
   - invoice_date: The date the invoice was issued (normalize to YYYY-MM-DD)
   - due_date: Payment due date (normalize to YYYY-MM-DD). If the document uses "Expiry Date", "Payment Due", or similar labels, map that value to due_date.
   - due_date_terms: Raw payment terms text exactly as printed (e.g. "Net 30", "Payment 30 days after invoice date"). Use null if not found.
   - po_reference: Purchase Order number referenced on the invoice
   - currency: ISO 4217 currency code (e.g., USD, EUR, GBP, INR). If only a currency symbol appears (e.g., "$" in the TOTAL line), infer the ISO code and use status "inferred" with confidence >= 0.90.
   - subtotal: Amount before tax and fees
   - tax_amount: Tax amount (sum of all tax components if multiple)
   - total_amount: Final total amount due
   - extra_charges: ALL fee/discount lines visible on the invoice NOT in line_items (shipping, handling, freight, surcharges, discounts). Use negative amounts for discounts.
   - line_items: Individual product/service rows in the main table

2. **For each field**, provide:
   - "value": The extracted value. Use `null` if not found. Dates as "YYYY-MM-DD". Amounts as numbers (not formatted strings).
   - "confidence": A score from 0.0 to 1.0 indicating your confidence in the extraction.
   - "status": One of:
     - "extracted": Value is directly visible and clearly readable in the document
     - "inferred": Value was derived from context (e.g., currency inferred from symbol, PO inferred from reference text)
     - "not_found": Value could not be located in the document — use `null` for value
     - "uncertain": A candidate value exists but the source is ambiguous or partially unreadable

3. **For each extra_charge**, provide:
   - "label": Text label as printed (e.g. "SHIPPING & HANDLING", "Freight", "Discount")
   - "amount": Numeric amount (negative for discounts)
   - "confidence": Confidence for this charge
   - "status": extracted | inferred

4. **For each line_item**, provide:
   - "description": Item/service description
   - "quantity": Numeric quantity (null if not listed)
   - "unit_price": Price per unit (null if not listed)
   - "amount": Line total amount
   - "confidence": Confidence for this line item

4. **CRITICAL RULES**:
   - NEVER invent or guess values. If a field is not visible, set value to null and status to "not_found".
   - If a date format is ambiguous (e.g., 03/04/2026), note lower confidence and status "uncertain".
   - If multiple candidate values exist for a field, choose the most likely one and note in confidence.
   - Be precise with amounts — extract exact numbers, don't round.
   - If the invoice has multiple tax components (e.g., CGST + SGST), sum them for tax_amount.
   - If there are handwritten corrections, prefer the correction and lower confidence.

## OUTPUT FORMAT

Return ONLY valid JSON matching this exact structure:
{
  "vendor_name": {"value": "...", "confidence": 0.95, "status": "extracted"},
  "invoice_number": {"value": "...", "confidence": 0.98, "status": "extracted"},
  "invoice_date": {"value": "YYYY-MM-DD", "confidence": 0.90, "status": "extracted"},
  "due_date": {"value": "YYYY-MM-DD", "confidence": 0.80, "status": "extracted"},
  "due_date_terms": {"value": "Net 30", "confidence": 0.90, "status": "extracted"},
  "po_reference": {"value": "...", "confidence": 0.70, "status": "inferred"},
  "currency": {"value": "USD", "confidence": 0.99, "status": "extracted"},
  "subtotal": {"value": 1000.00, "confidence": 0.95, "status": "extracted"},
  "tax_amount": {"value": 80.00, "confidence": 0.88, "status": "extracted"},
  "total_amount": {"value": 1080.00, "confidence": 0.97, "status": "extracted"},
  "extra_charges": [
    {"label": "SHIPPING & HANDLING", "amount": 3.49, "confidence": 0.95, "status": "extracted"}
  ],
  "line_items": [
    {"description": "...", "quantity": 1, "unit_price": 1000.00, "amount": 1000.00, "confidence": 0.90}
  ]
}
"""


class Extractor:
    """Runs LLM Call #1 — Primary invoice extraction with strict schema validation."""

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    async def extract(self, invoice_images: list[bytes]) -> InvoiceExtraction:
        """
        Extract structured invoice data from page images.

        Args:
            invoice_images: List of invoice page images (PNG bytes).
                           Only pages classified as 'line_items' should be passed.

        Returns:
            InvoiceExtraction with field-level confidence and status.

        Raises:
            ExtractionError: If extraction fails after validation.
        """
        logger.info(f"Starting primary extraction on {len(invoice_images)} page(s)")

        raw_response = await self.provider.extract_invoice(
            images=invoice_images,
            prompt=EXTRACTION_PROMPT,
        )

        return self._parse_extraction(raw_response)

    def _parse_extraction(self, raw_json: str) -> InvoiceExtraction:
        """
        Parse and validate the LLM extraction response into the strict schema.

        Handles various response formats gracefully.
        """
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as e:
            raise ExtractionError(f"LLM returned invalid JSON: {e}")

        if not isinstance(data, dict):
            raise ExtractionError(f"Expected JSON object, got {type(data).__name__}")

        try:
            extraction = InvoiceExtraction(
                vendor_name=self._parse_field(data.get("vendor_name")),
                invoice_number=self._parse_field(data.get("invoice_number")),
                invoice_date=self._parse_field(data.get("invoice_date")),
                due_date=self._parse_field(data.get("due_date")),
                due_date_terms=self._parse_field(data.get("due_date_terms")),
                po_reference=self._parse_field(data.get("po_reference")),
                currency=self._parse_field(data.get("currency")),
                subtotal=self._parse_field(data.get("subtotal")),
                tax_amount=self._parse_field(data.get("tax_amount")),
                total_amount=self._parse_field(data.get("total_amount")),
                extra_charges=self._parse_extra_charges(data.get("extra_charges", [])),
                line_items=self._parse_line_items(data.get("line_items", [])),
                typed_references=self._parse_typed_references(
                    data.get("typed_references", [])
                ),
                custom_facts=self._parse_custom_facts(data.get("custom_facts", [])),
                tax_components=self._parse_tax_components(data.get("tax_components", [])),
                document_class=str(data.get("document_class", "invoice")),
                reconciliation_mode=str(data.get("reconciliation_mode", "tax_exclusive")),
                locale_hints=data.get("locale_hints") or {},
            )

            logger.info(
                f"Extraction parsed: "
                f"vendor={extraction.vendor_name.value}, "
                f"invoice_num={extraction.invoice_number.value}, "
                f"total={extraction.total_amount.value}"
            )
            return extraction

        except Exception as e:
            raise ExtractionError(f"Failed to parse extraction into schema: {e}")

    def _parse_field(self, field_data) -> FieldExtraction:
        """Parse a single field extraction, handling various input formats."""
        if field_data is None:
            return FieldExtraction(value=None, confidence=0.0, status="not_found")

        if isinstance(field_data, dict):
            value = field_data.get("value")
            confidence = float(field_data.get("confidence", 0.0))
            status = field_data.get("status", "extracted")

            # Validate status
            valid_statuses = {"extracted", "inferred", "not_found", "uncertain"}
            if status not in valid_statuses:
                status = "extracted" if value is not None else "not_found"

            # Clamp confidence
            confidence = max(0.0, min(1.0, confidence))

            return FieldExtraction(value=value, confidence=confidence, status=status)

        # Handle raw value (model didn't use the schema properly)
        return FieldExtraction(
            value=field_data,
            confidence=0.5,  # Lower confidence for non-schema response
            status="extracted" if field_data is not None else "not_found",
        )

    def _parse_extra_charges(self, charges_data) -> list[ExtraCharge]:
        """Parse extra charge lines from extraction response."""
        if not isinstance(charges_data, list):
            return []

        charges = []
        for item in charges_data:
            if not isinstance(item, dict):
                continue
            amount = self._safe_float(item.get("amount"))
            if amount is None:
                continue
            status = item.get("status", "extracted")
            if status not in {"extracted", "inferred", "not_found", "uncertain"}:
                status = "extracted"
            charges.append(
                ExtraCharge(
                    label=str(item.get("label", "")),
                    category="other",
                    amount=amount,
                    confidence=float(item.get("confidence", 0.5)),
                    status=status,
                )
            )
        return charges

    def _parse_line_items(self, items_data) -> list[LineItem]:
        """Parse line items from the extraction response."""
        if not isinstance(items_data, list):
            return []

        line_items = []
        for item in items_data:
            if not isinstance(item, dict):
                continue
            try:
                line_items.append(
                    LineItem(
                        description=item.get("description"),
                        quantity=self._safe_float(item.get("quantity")),
                        unit_price=self._safe_float(item.get("unit_price")),
                        amount=self._safe_float(item.get("amount")),
                        sku=item.get("sku"),
                        uom=item.get("uom"),
                        tax_amount=self._safe_float(item.get("tax_amount")),
                        po_hint=item.get("po_hint"),
                        confidence=float(item.get("confidence", 0.5)),
                        raw_values=item.get("raw_values") or {},
                    )
                )
            except (ValueError, TypeError) as e:
                logger.warning(f"Skipping malformed line item: {e}")
                continue

        return line_items

    def _parse_typed_references(self, refs_data) -> list[TypedReference]:
        if not isinstance(refs_data, list):
            return []
        refs = []
        for item in refs_data:
            if not isinstance(item, dict):
                continue
            refs.append(
                TypedReference(
                    reference_type=str(item.get("reference_type", "other")),
                    value=item.get("value"),
                    raw_label=item.get("raw_label"),
                    confidence=float(item.get("confidence", 0.5)),
                    status=item.get("status", "extracted"),
                    page=item.get("page"),
                )
            )
        return refs

    def _parse_custom_facts(self, facts_data) -> list[CustomFact]:
        if not isinstance(facts_data, list):
            return []
        facts = []
        for item in facts_data:
            if not isinstance(item, dict):
                continue
            facts.append(
                CustomFact(
                    label=str(item.get("label", "")),
                    value=item.get("value"),
                    confidence=float(item.get("confidence", 0.5)),
                    page=item.get("page"),
                )
            )
        return facts

    def _parse_tax_components(self, tax_data) -> list[TaxComponent]:
        if not isinstance(tax_data, list):
            return []
        components = []
        for item in tax_data:
            if not isinstance(item, dict):
                continue
            components.append(
                TaxComponent(
                    label=str(item.get("label", "")),
                    rate=self._safe_float(item.get("rate")),
                    amount=self._safe_float(item.get("amount")),
                    jurisdiction=item.get("jurisdiction"),
                    confidence=float(item.get("confidence", 0.5)),
                )
            )
        return components

    def _safe_float(self, value) -> float | None:
        """Safely convert a value to float, returning None for non-numeric."""
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None


class ExtractionError(Exception):
    """Raised when invoice extraction fails (malformed output, parse errors)."""
    pass
