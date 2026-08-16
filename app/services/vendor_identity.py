"""
Shared vendor identity normalization and resolution for import + matching.
"""

from __future__ import annotations

import re

CORPORATE_SUFFIXES = [
    r"\bllc\b",
    r"\bltd\b",
    r"\binc\b",
    r"\bcorp\b",
    r"\bcorporation\b",
    r"\bpvt\b",
    r"\bprivate\b",
    r"\blimited\b",
    r"\bco\b",
    r"\bcompany\b",
    r"\bgroup\b",
    r"\bservices\b",
    r"\bsolutions\b",
    r"\btechnologies\b",
    r"\b&\b",
    r"\band\b",
]


def normalize_vendor_name(name: str) -> str:
    """Canonical vendor name key used at ingest and match time."""
    if not name:
        return ""
    normalized = name.upper().strip()
    normalized = re.sub(r"[.,;:'\"\-]", " ", normalized)
    for suffix in CORPORATE_SUFFIXES:
        normalized = re.sub(suffix, "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def vendor_names_equivalent(a: str | None, b: str | None) -> bool:
    """True when two vendor display names refer to the same canonical identity."""
    if not a or not b:
        return False
    return normalize_vendor_name(a) == normalize_vendor_name(b)


def ocr_vendor_aliases(vendor_name: str) -> list[str]:
    """Common OCR/display variants for vendor aliases (e.g. comma placement)."""
    if not vendor_name:
        return []
    aliases: list[str] = []
    stripped = vendor_name.strip()
    if "," not in stripped:
        parts = stripped.split()
        if len(parts) >= 2:
            aliases.append(f"{parts[0]}, {' '.join(parts[1:])}")
    else:
        aliases.append(stripped.replace(",", ""))
    return [a for a in aliases if a and a != stripped]
