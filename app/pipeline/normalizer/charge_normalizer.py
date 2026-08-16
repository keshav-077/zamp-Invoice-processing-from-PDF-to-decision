"""Normalize charge labels to categories using config aliases."""

import logging

from app.models.extraction import ExtraCharge, InvoiceExtraction
from app.pipeline.policy_loader import load_field_aliases

logger = logging.getLogger(__name__)


def categorize_charge_label(label: str) -> str:
    """Map a printed label to a charge category via config."""
    if not label:
        return "other"

    normalized = label.lower().strip()
    aliases = load_field_aliases()
    categories = aliases.get("charge_categories", {})

    for category, patterns in categories.items():
        for pattern in patterns:
            if pattern.lower() in normalized or normalized in pattern.lower():
                return category

    return "other"


def normalize_charges(extraction: InvoiceExtraction) -> InvoiceExtraction:
    """Apply category normalization to all extra charges."""
    normalized: list[ExtraCharge] = []
    for charge in extraction.extra_charges:
        category = categorize_charge_label(charge.label)
        normalized.append(
            ExtraCharge(
                label=charge.label,
                category=category,
                amount=charge.amount,
                confidence=charge.confidence,
                status=charge.status,
            )
        )
    extraction.extra_charges = normalized
    return extraction
