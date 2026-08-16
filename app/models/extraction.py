"""
InvoiceFlow AI — Invoice Extraction Data Models

Defines the strict schema for LLM Call #1 (Primary Extraction).
Every field includes value, confidence, and extraction status.
"""

from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field


class FieldExtraction(BaseModel):
    """A single extracted field with confidence and status metadata."""

    value: Any | None = Field(
        default=None,
        description="Extracted value. None if not found."
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Model-reported confidence score (0.0–1.0). Routing signal, not calibrated probability."
    )
    status: Literal["extracted", "inferred", "not_found", "uncertain"] = Field(
        default="not_found",
        description=(
            "extracted: directly visible and identified. "
            "inferred: derived from context (less trustworthy). "
            "not_found: not located in document. "
            "uncertain: candidate value exists but source is ambiguous."
        )
    )


class LineItem(BaseModel):
    """A single invoice line item."""

    description: str | None = Field(default=None, description="Line item description")
    quantity: float | None = Field(default=None, description="Quantity")
    unit_price: float | None = Field(default=None, description="Price per unit")
    amount: float | None = Field(default=None, description="Line total amount")
    sku: str | None = Field(default=None, description="SKU / part number if printed")
    uom: str | None = Field(default=None, description="Unit of measure")
    tax_amount: float | None = Field(default=None, description="Line tax if shown")
    po_hint: str | None = Field(default=None, description="PO reference hint on line")
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence score for this line item extraction",
    )
    raw_values: dict[str, Any] = Field(
        default_factory=dict,
        description="Raw printed values before normalization",
    )


class TypedReference(BaseModel):
    """A typed reference extracted from invoice (PO, order, contract, etc.)."""

    reference_type: str = Field(
        description="order_ref | contract_ref | customer_po | release_ref | other"
    )
    value: str | None = None
    raw_label: str | None = Field(default=None, description="Label as printed on invoice")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    status: Literal["extracted", "inferred", "not_found", "uncertain"] = "not_found"
    page: int | None = Field(default=None, description="Source page number if known")


class CustomFact(BaseModel):
    """Unrecognized invoice field preserved for audit and custom mapping."""

    label: str
    value: Any = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    page: int | None = None


class TaxComponent(BaseModel):
    """Individual tax line (CGST, VAT, etc.)."""

    label: str = ""
    rate: float | None = None
    amount: float | None = None
    jurisdiction: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ExtraCharge(BaseModel):
    """A fee, surcharge, shipping, or discount line visible on the invoice."""

    label: str = Field(default="", description="Label as printed on invoice")
    category: str = Field(
        default="other",
        description="Normalized category: shipping, handling, tax, discount, surcharge, other"
    )
    amount: float = Field(description="Charge amount (discounts are negative)")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    status: Literal["extracted", "inferred", "not_found", "uncertain"] = Field(
        default="extracted"
    )


class InvoiceExtraction(BaseModel):
    """
    Complete structured extraction from an invoice document.

    This is the target schema for LLM Call #1.
    Dates are normalized to YYYY-MM-DD. Currency uses ISO 4217.
    Amounts are numeric (not formatted strings).
    """

    vendor_name: FieldExtraction = Field(default_factory=FieldExtraction)
    invoice_number: FieldExtraction = Field(default_factory=FieldExtraction)
    invoice_date: FieldExtraction = Field(default_factory=FieldExtraction)
    due_date: FieldExtraction = Field(default_factory=FieldExtraction)
    due_date_terms: FieldExtraction = Field(
        default_factory=FieldExtraction,
        description="Raw payment terms text e.g. Net 30, 30 days after invoice date"
    )
    po_reference: FieldExtraction = Field(default_factory=FieldExtraction)
    currency: FieldExtraction = Field(default_factory=FieldExtraction)
    subtotal: FieldExtraction = Field(default_factory=FieldExtraction)
    tax_amount: FieldExtraction = Field(default_factory=FieldExtraction)
    total_amount: FieldExtraction = Field(default_factory=FieldExtraction)
    extra_charges: list[ExtraCharge] = Field(
        default_factory=list,
        description="Shipping, handling, surcharges, discounts visible on invoice"
    )
    line_items: list[LineItem] = Field(
        default_factory=list,
        description="Extracted line items from the invoice",
    )
    typed_references: list[TypedReference] = Field(
        default_factory=list,
        description="All typed references (order, contract, customer PO, etc.)",
    )
    custom_facts: list[CustomFact] = Field(
        default_factory=list,
        description="Additional fields not in canonical schema",
    )
    tax_components: list[TaxComponent] = Field(
        default_factory=list,
        description="Itemized tax breakdown when present",
    )
    document_class: str = Field(
        default="invoice",
        description="invoice | credit_memo | debit_memo | statement | proforma",
    )
    reconciliation_mode: str = Field(
        default="tax_exclusive",
        description="tax_exclusive | tax_inclusive | multi_tax | lines_only | header_only",
    )
    locale_hints: dict[str, str] = Field(
        default_factory=dict,
        description="Detected locale hints (decimal_sep, date_format, language)",
    )
