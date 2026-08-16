"""Imported invoice/transaction source records (canonical, PO relationship optional)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SourceRecord(BaseModel):
    """Canonical imported transaction — PO link may remain unresolved."""

    source_record_id: str
    company_id: str = "DEFAULT"
    record_type: str  # invoice_transaction | invoice_with_po_reference
    vendor_id: str | None = None
    vendor_name: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None
    invoice_total: float | None = None
    invoice_subtotal: float | None = None
    currency: str = "USD"
    po_reference: str | None = None
    po_reference_status: str = "unresolved"  # unresolved | not_applicable
    status: str = "active"
    import_batch_id: str | None = None
    source_row_index: int | None = None
    metadata_json: str = "{}"
    created_at: str | None = None

    model_config = {"extra": "ignore"}
