"""
InvoiceFlow AI — Purchase Order & Vendor Data Models

Defines the enterprise data structures for:
- Vendor Master records
- Purchase Order headers and lines
- Goods Receipt Notes (GRN)

Note: ``PurchaseOrder`` is PO *master* data. User CSV invoice rows are **mirrored**
into ``purchase_orders`` on import (same table as developer seed). ``source_records``
retains the audit copy of imported transactions.
"""

from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


class Vendor(BaseModel):
    """Vendor Master record."""
    vendor_id: str = Field(description="Unique vendor identifier")
    name: str = Field(description="Official vendor name")
    normalized_name: str = Field(description="Normalized name for matching (uppercased, stripped)")
    aliases: list[str] = Field(default_factory=list, description="Known alternative names")
    tax_id: str | None = Field(default=None, description="Tax ID / GSTIN / PAN")
    supplier_code: str | None = Field(default=None, description="Internal supplier code")
    status: Literal["active", "inactive", "suspended"] = Field(
        default="active", description="Vendor status in master"
    )


class POLine(BaseModel):
    """A single line item on a Purchase Order."""
    line_number: int = Field(description="PO line number (1-indexed)")
    description: str = Field(description="Item/service description")
    sku: str | None = Field(default=None, description="SKU / Part Number / Catalog ID")
    quantity: float = Field(description="Ordered quantity")
    unit_price: float = Field(description="Price per unit")
    amount: float = Field(description="Line total (quantity × unit_price)")
    uom: str = Field(default="each", description="Unit of Measure")


class PurchaseOrder(BaseModel):
    """Purchase Order header with lines and balance tracking."""
    po_number: str = Field(description="Unique PO identifier")
    vendor_id: str = Field(description="Vendor ID from Vendor Master")
    vendor_name: str = Field(description="Vendor name (denormalized)")
    total_amount: float = Field(description="Total PO value")
    currency: str = Field(default="USD", description="ISO 4217 currency code")
    status: Literal["open", "closed", "cancelled", "closed_for_invoicing"] = Field(
        default="open", description="PO lifecycle status"
    )
    po_type: Literal["standard", "blanket"] = Field(
        default="standard", description="PO type — standard (fixed) or blanket (recurring)"
    )
    issue_date: str = Field(description="PO issue date (YYYY-MM-DD)")
    expiry_date: str | None = Field(default=None, description="PO expiry date")
    lines: list[POLine] = Field(default_factory=list, description="PO line items")

    # --- Balance Tracking ---
    received_amount: float = Field(default=0.0, description="Total GRN-confirmed amount")
    previously_invoiced: float = Field(default=0.0, description="Sum of prior invoice amounts")

    @property
    def remaining_amount(self) -> float:
        """Calculate remaining balance available for invoicing."""
        return self.total_amount - self.previously_invoiced


class GRNRecord(BaseModel):
    """Goods Receipt Note — confirms physical delivery against a PO."""
    grn_id: str = Field(description="Unique GRN identifier")
    po_number: str = Field(description="Associated PO number")
    received_date: str = Field(description="Date goods/services were received")
    received_amount: float = Field(description="Total value received")
    status: Literal["confirmed", "partial", "pending"] = Field(
        default="confirmed", description="GRN status"
    )
