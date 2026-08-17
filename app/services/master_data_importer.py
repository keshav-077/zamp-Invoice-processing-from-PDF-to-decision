"""
Runtime CSV/XLSX master data import with preview, validation, and idempotent upsert.
"""

from __future__ import annotations

import io
import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any

import pandas as pd

from app.db import repository
from app.services.vendor_identity import normalize_vendor_name

logger = logging.getLogger(__name__)

DEFAULT_COMPANY_ID = "DEFAULT"

VENDOR_ALIASES = {
    "vendor_id": ["vendor_id", "vendorid", "supplier_id", "id"],
    "name": ["name", "vendor_name", "supplier_name", "vendor"],
    "tax_id": ["tax_id", "taxid", "gstin", "vat", "ein"],
    "supplier_code": ["supplier_code", "vendor_code", "supplier_id", "code"],
    "aliases": ["aliases", "alias", "aka"],
    "status": ["status"],
}

PO_ALIASES = {
    "po_number": ["po_number", "po", "po_no", "purchase_order", "ponumber"],
    "vendor_id": ["vendor_id", "supplier_id"],
    "vendor_name": ["vendor_name", "supplier_name", "vendor"],
    "supplier_code": ["supplier_code", "vendor_code"],
    "total_amount": ["total_amount", "po_total", "amount", "total"],
    "currency": ["currency", "curr"],
    "status": ["status"],
    "po_type": ["po_type", "type"],
    "issue_date": ["issue_date", "po_date", "date"],
    "expiry_date": ["expiry_date", "expiration_date"],
    "received_amount": ["received_amount"],
    "previously_invoiced": ["previously_invoiced", "invoiced_to_date"],
}

LINE_ALIASES = {
    "po_number": ["po_number", "po", "po_no"],
    "line_number": ["line_number", "line", "line_no", "lineno"],
    "description": ["description", "item_description", "desc"],
    "sku": ["sku", "item_code", "part_number"],
    "quantity": ["quantity", "qty"],
    "unit_price": ["unit_price", "price", "unit_cost"],
    "amount": ["amount", "line_total", "extended_amount"],
    "uom": ["uom", "unit"],
}

GRN_ALIASES = {
    "grn_id": ["grn_id", "receipt_id", "grn"],
    "po_number": ["po_number", "po"],
    "received_date": ["received_date", "receipt_date"],
    "received_amount": ["received_amount", "amount"],
    "status": ["status"],
}

REF_ALIASES = {
    "po_number": ["po_number", "po"],
    "reference_type": ["reference_type", "ref_type", "type"],
    "reference_value": ["reference_value", "ref", "reference", "order_ref", "contract_ref"],
}


def _normalize_columns(df: pd.DataFrame, alias_map: dict[str, list[str]]) -> pd.DataFrame:
    rename: dict[str, str] = {}
    lower_cols = {str(c).strip().lower().replace(" ", "_"): c for c in df.columns}
    for canonical, aliases in alias_map.items():
        for alias in aliases:
            if alias in lower_cols:
                rename[lower_cols[alias]] = canonical
                break
    return df.rename(columns=rename)


def _parse_file(content: bytes, filename: str) -> dict[str, pd.DataFrame]:
    from app.services.upload_files import parse_upload_workbook

    return parse_upload_workbook(content, filename)


def _sheet(df_map: dict[str, pd.DataFrame], *names: str) -> pd.DataFrame | None:
    for name in names:
        if name in df_map:
            return df_map[name]
    return None


def _safe_str(val: Any) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return str(val).strip()


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _next_vendor_id(company_id: str) -> str:
    existing = repository.get_all_vendors(company_id=company_id)
    nums = []
    for v in existing:
        vid = v.get("vendor_id", "")
        if vid.startswith("V") and vid[1:].isdigit():
            nums.append(int(vid[1:]))
    n = max(nums) + 1 if nums else 1
    return f"V{n:03d}"


def _resolve_vendor_key(
    company_id: str,
    row: dict,
    vendor_by_id: dict[str, dict],
    vendor_by_supplier: dict[str, dict],
    vendor_by_tax: dict[str, dict],
    vendor_by_norm: dict[str, dict],
) -> tuple[str | None, str | None]:
    """Return (vendor_id, error)."""
    supplier_code = _safe_str(row.get("supplier_code"))
    tax_id = _safe_str(row.get("tax_id"))
    name = _safe_str(row.get("name"))
    vendor_id = _safe_str(row.get("vendor_id"))

    if supplier_code and supplier_code in vendor_by_supplier:
        return vendor_by_supplier[supplier_code]["vendor_id"], None
    if tax_id and tax_id in vendor_by_tax:
        return vendor_by_tax[tax_id]["vendor_id"], None
    if name:
        norm = normalize_vendor_name(name)
        if norm in vendor_by_norm:
            return vendor_by_norm[norm]["vendor_id"], None
    if vendor_id and vendor_id in vendor_by_id:
        return vendor_id, None
    if vendor_id:
        return vendor_id, None  # new explicit id
    if name:
        return _next_vendor_id(company_id), None
    return None, "Vendor row missing name and identifiers"


class MasterDataImporter:
    """Parse, validate, preview, and commit PO master data (adaptive backend)."""

    def __init__(self) -> None:
        from app.services.adaptive_importer import AdaptiveImporter

        self._adaptive = AdaptiveImporter()

    def preview(
        self,
        content: bytes,
        filename: str,
        company_id: str = DEFAULT_COMPANY_ID,
        confirmed_mappings: list[dict] | None = None,
    ) -> dict:
        return self._adaptive.preview(content, filename, company_id, confirmed_mappings)

    def commit(
        self,
        content: bytes,
        filename: str,
        company_id: str = DEFAULT_COMPANY_ID,
        confirmed_mappings: list[dict] | None = None,
    ) -> dict:
        return self._adaptive.commit(content, filename, company_id, confirmed_mappings)

