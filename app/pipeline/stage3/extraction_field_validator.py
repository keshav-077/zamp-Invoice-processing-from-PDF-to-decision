"""
Stage 3 — flags for missing or weak extraction fields (Spec Section 20).
"""

from __future__ import annotations

from app.models.evidence import EvidenceProfile
from app.models.extraction import InvoiceExtraction
from app.models.validation import ValidationCheck


def check_extraction_fields(
    extraction: InvoiceExtraction,
    evidence_profile: EvidenceProfile | None = None,
) -> tuple[ValidationCheck, list[str]]:
    """Return validation check and reason codes for missing invoice identity fields."""
    reason_codes: list[str] = []
    evidence: list[str] = []

    field_checks = [
        ("invoice_number", extraction.invoice_number, "missing_invoice_number"),
        ("invoice_date", extraction.invoice_date, "missing_invoice_date"),
        ("currency", extraction.currency, "missing_currency"),
    ]

    flags = 0
    for label, field, code in field_checks:
        if field.value is None or field.status == "not_found":
            reason_codes.append(code)
            evidence.append(f"Extraction missing: {label}")
            flags += 1
        elif field.status == "uncertain":
            reason_codes.append(f"{code}_uncertain")
            evidence.append(f"Extraction uncertain: {label}")
            flags += 1

    if evidence_profile and evidence_profile.reconciliation_status == "residual_review":
        reason_codes.append("reconciliation_residual")
        evidence.append("Arithmetic reconciliation has unexplained residual")

    if flags == 0:
        status = "PASS"
        reason_code = ""
    elif flags >= 2:
        status = "FLAG"
        reason_code = "EXTRACTION_FIELDS_INCOMPLETE"
    else:
        status = "FLAG"
        reason_code = reason_codes[0].upper()

    check = ValidationCheck(
        check_id="extraction_completeness",
        status=status,
        reason_code=reason_code or "EXTRACTION_OK",
        evidence=evidence or ["Required extraction fields present for validation"],
    )
    return check, reason_codes
