"""Mirror imported source_records into purchase_orders + vendors (unified PO master)."""

from __future__ import annotations

import json
from datetime import datetime

from app.services.import_normalize import safe_str, valid_po_number
from app.services.master_data_importer import _next_vendor_id
from app.services.vendor_identity import normalize_vendor_name, vendor_names_equivalent


def mirrored_po_number(source_record_id: str, po_reference: str | None) -> str:
    """Stable PO key: explicit import PO ref or generated IMP-* id."""
    if po_reference:
        normalized = valid_po_number(po_reference)
        if normalized:
            return normalized
    return f"IMP-{source_record_id}"


def build_mirrored_po_row(
    *,
    source_record_id: str,
    company_id: str,
    vendor_id: str,
    vendor_name: str,
    invoice_total: float,
    currency: str,
    po_reference: str | None,
    import_batch_id: str | None,
    invoice_number: str | None,
    invoice_date: str | None,
    po_numbers_seen: set[str],
) -> dict | None:
    """Build purchase_orders row equivalent to developer seed PO master."""
    if invoice_total <= 0:
        return None

    po_number = mirrored_po_number(source_record_id, po_reference)
    if po_number in po_numbers_seen:
        po_number = f"IMP-{source_record_id}"

    mirror_meta = {
        "import_derived": True,
        "source_record_id": source_record_id,
        "import_batch_id": import_batch_id,
        "mirror_reason": "user_csv_equivalent_to_po_master",
        "linked_invoice_number": invoice_number,
        "linked_invoice_date": invoice_date,
    }

    return {
        "po_number": po_number,
        "company_id": company_id,
        "vendor_id": vendor_id,
        "vendor_name": vendor_name,
        "total_amount": float(invoice_total),
        "currency": currency or "USD",
        "status": "open",
        "po_type": "blanket",
        "issue_date": invoice_date or datetime.utcnow().strftime("%Y-%m-%d"),
        "expiry_date": None,
        "received_amount": 0.0,
        "previously_invoiced": 0.0,
        "metadata_json": json.dumps(mirror_meta),
    }


def ensure_vendor_for_mirror(
    company_id: str,
    vendor_id: str | None,
    vendor_name: str,
    vendor_by_id: dict,
    vendor_by_supplier: dict,
    vendor_by_tax: dict,
    vendor_by_norm: dict,
    vendor_rows: list[dict],
    metadata: dict,
    ensure_vendor_fn,
) -> str | None:
    """Return vendor_id for mirror, creating vendor row if needed."""
    if not vendor_name:
        return None
    if vendor_id and vendor_id in vendor_by_id:
        existing = vendor_by_id[vendor_id]
        if vendor_names_equivalent(existing.get("name"), vendor_name):
            return vendor_id

    norm = normalize_vendor_name(vendor_name)
    if norm in vendor_by_norm:
        return vendor_by_norm[norm]["vendor_id"]

    if vendor_id and vendor_id not in vendor_by_id:
        new_id = vendor_id
    else:
        new_id = _next_vendor_id(company_id)
    ensure_vendor_fn(
        company_id,
        new_id,
        vendor_name,
        "",
        vendor_by_id,
        vendor_by_supplier,
        vendor_by_tax,
        vendor_by_norm,
        vendor_rows,
        metadata,
    )
    return new_id
