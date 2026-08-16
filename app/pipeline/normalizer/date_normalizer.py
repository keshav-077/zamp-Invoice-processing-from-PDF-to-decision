"""Parse and normalize invoice dates including relative payment terms."""

import logging
import re
from datetime import datetime, timedelta

from app.models.extraction import FieldExtraction, InvoiceExtraction
from app.pipeline.policy_loader import load_field_aliases

logger = logging.getLogger(__name__)


def parse_date_string(value: str) -> str | None:
    """Parse common date string formats to YYYY-MM-DD."""
    if not value or not isinstance(value, str):
        return None

    cleaned = value.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", cleaned):
        return cleaned

    aliases = load_field_aliases()
    for fmt in aliases.get("date_formats", []):
        try:
            return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return None


def compute_due_date_from_terms(invoice_date: str, terms_text: str) -> str | None:
    """Compute due date from Net 30 / N days after invoice date patterns."""
    if not invoice_date or not terms_text:
        return None

    base = parse_date_string(invoice_date)
    if not base:
        return None

    text = terms_text.lower()
    aliases = load_field_aliases()
    days: int | None = None

    for pattern in aliases.get("due_date_terms_patterns", []):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                days = int(match.group(1))
                break
            except (IndexError, ValueError):
                continue

    if days is None:
        if "net 30" in text or text.strip() == "net30":
            days = 30
        elif "net 45" in text:
            days = 45
        elif "net 60" in text:
            days = 60
        elif "net 15" in text:
            days = 15

    if days is None:
        return None

    base_dt = datetime.strptime(base, "%Y-%m-%d")
    due = base_dt + timedelta(days=days)
    logger.info(f"Computed due date: {due.strftime('%Y-%m-%d')} from terms '{terms_text}'")
    return due.strftime("%Y-%m-%d")


def normalize_dates(extraction: InvoiceExtraction) -> InvoiceExtraction:
    """Normalize invoice_date and compute due_date from terms when needed."""
    if extraction.invoice_date.value and isinstance(extraction.invoice_date.value, str):
        parsed = parse_date_string(str(extraction.invoice_date.value))
        if parsed and parsed != extraction.invoice_date.value:
            extraction.invoice_date.value = parsed

    if extraction.due_date.value and isinstance(extraction.due_date.value, str):
        parsed = parse_date_string(str(extraction.due_date.value))
        if parsed:
            extraction.due_date.value = parsed

    if (
        (extraction.due_date.value is None or extraction.due_date.status == "not_found")
        and extraction.due_date_terms.value
        and extraction.invoice_date.value
    ):
        computed = compute_due_date_from_terms(
            str(extraction.invoice_date.value),
            str(extraction.due_date_terms.value),
        )
        if computed:
            extraction.due_date = FieldExtraction(
                value=computed,
                confidence=max(extraction.due_date_terms.confidence, 0.85),
                status="inferred",
            )

    return extraction
