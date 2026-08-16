"""Locale-aware normalization for currencies, amounts, dates, and UOM."""

from __future__ import annotations

import re
from typing import Any

from app.models.extraction import FieldExtraction, InvoiceExtraction, LineItem

CURRENCY_SYMBOL_MAP = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "₹": "INR",
    "¥": "JPY",
    "C$": "CAD",
    "A$": "AUD",
}

UOM_ALIASES = {
    "ea": "each",
    "each": "each",
    "pc": "each",
    "pcs": "each",
    "unit": "each",
    "hr": "hour",
    "hrs": "hour",
    "hour": "hour",
    "kg": "kg",
    "lb": "lb",
    "lbs": "lb",
}


def parse_amount(raw: Any, locale_hints: dict | None = None) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if not s:
        return None
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    s = re.sub(r"[^\d,.\-]", "", s)
    if not s:
        return None
    decimal_sep = (locale_hints or {}).get("decimal_sep", ".")
    if decimal_sep == "," and s.count(",") == 1 and s.count(".") == 0:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        val = float(s)
        return -val if negative else val
    except ValueError:
        return None


def normalize_currency_field(field: FieldExtraction) -> FieldExtraction:
    if field.value is None:
        return field
    val = str(field.value).strip().upper()
    if len(val) == 3 and val.isalpha():
        field.value = val
        return field
    for sym, code in CURRENCY_SYMBOL_MAP.items():
        if sym in str(field.value):
            field.value = code
            if field.status == "not_found":
                field.status = "inferred"
            return field
    return field


def normalize_uom(uom: str | None) -> str | None:
    if not uom:
        return None
    key = uom.strip().lower()
    return UOM_ALIASES.get(key, key)


def normalize_line_item(item: LineItem, locale_hints: dict | None = None) -> LineItem:
    if item.amount is None and item.quantity and item.unit_price:
        item.amount = round(item.quantity * item.unit_price, 4)
    if isinstance(item.amount, str):
        item.amount = parse_amount(item.amount, locale_hints)
    if isinstance(item.quantity, str):
        item.quantity = parse_amount(item.quantity, locale_hints)
    if isinstance(item.unit_price, str):
        item.unit_price = parse_amount(item.unit_price, locale_hints)
    item.uom = normalize_uom(item.uom)
    return item


def infer_reconciliation_mode(extraction: InvoiceExtraction) -> str:
    if extraction.tax_components and len(extraction.tax_components) > 1:
        return "multi_tax"
    if extraction.line_items and not extraction.subtotal.value and extraction.total_amount.value:
        return "lines_only"
    if extraction.total_amount.value and not extraction.line_items:
        return "header_only"
    sub = extraction.subtotal.value
    tax = extraction.tax_amount.value or 0
    total = extraction.total_amount.value
    if sub and total and tax:
        if abs(float(sub) + float(tax) - float(total)) < 0.02:
            return "tax_exclusive"
        if abs(float(sub) - float(total)) < 0.02:
            return "tax_inclusive"
    return extraction.reconciliation_mode or "tax_exclusive"


def normalize_extraction_locale(extraction: InvoiceExtraction) -> InvoiceExtraction:
    hints = extraction.locale_hints or {}
    extraction.currency = normalize_currency_field(extraction.currency)
    for field_name in ("subtotal", "tax_amount", "total_amount"):
        f = getattr(extraction, field_name)
        if f.value is not None and not isinstance(f.value, (int, float)):
            parsed = parse_amount(f.value, hints)
            if parsed is not None:
                f.value = parsed
                setattr(extraction, field_name, f)
    extraction.line_items = [
        normalize_line_item(li, hints) for li in extraction.line_items
    ]
    extraction.reconciliation_mode = infer_reconciliation_mode(extraction)
    return extraction
