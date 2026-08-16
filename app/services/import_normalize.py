"""Shared normalization helpers for master data import."""

from __future__ import annotations

from typing import Any

import pandas as pd

DEFAULT_PO_SENTINELS = frozenset(
    {"none", "n/a", "na", "null", "nil", "-", "nan", "n.a.", "n.a", "missing", "not applicable"}
)


def safe_str(val: Any) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return str(val).strip()


def safe_float(val: Any, default: float = 0.0) -> float:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def valid_po_number(val: Any, sentinels: frozenset[str] | None = None) -> str | None:
    """Return normalized PO number or None for placeholders like NONE/N/A."""
    tokens = sentinels or DEFAULT_PO_SENTINELS
    s = safe_str(val)
    if not s:
        return None
    if s.lower() in tokens:
        return None
    return s


def normalize_po_reference(val: Any, sentinels: frozenset[str] | None = None) -> str | None:
    """Normalize PO reference for invoice rows (same sentinel rules, no PO master validation)."""
    return valid_po_number(val, sentinels)
