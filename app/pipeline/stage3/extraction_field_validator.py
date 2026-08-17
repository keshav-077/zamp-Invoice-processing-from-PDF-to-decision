"""
Stage 3 — flags for missing or weak extraction fields (Spec Section 20).
"""

from __future__ import annotations

from app.models.evidence import EvidenceProfile
from app.models.extraction import InvoiceExtraction
from app.models.validation import ValidationCheck
from app.pipeline.policy_loader import load_routing_policy


PO_RESOLVED_STATUSES = {"matched", "high_confidence_match", "partial_match"}


def _po_match_resolves_identity(match_status: str | None) -> bool:
    return bool(match_status and match_status in PO_RESOLVED_STATUSES)


def check_extraction_fields(
    extraction: InvoiceExtraction,
    evidence_profile: EvidenceProfile | None = None,
    match_status: str | None = None,
) -> tuple[ValidationCheck, list[str]]:
    """Return validation check and reason codes for missing invoice identity fields."""
    policy = load_routing_policy()
    optional_identity = set(
        policy.get(
            "optional_identity_fields",
            ["invoice_number", "invoice_date"],
        )
    )
    po_resolved = _po_match_resolves_identity(match_status)

    reason_codes: list[str] = []
    evidence: list[str] = []
    blocking_flags = 0

    field_checks = [
        ("invoice_number", extraction.invoice_number, "missing_invoice_number"),
        ("invoice_date", extraction.invoice_date, "missing_invoice_date"),
        ("currency", extraction.currency, "missing_currency"),
    ]

    for label, field, code in field_checks:
        optional = label in optional_identity and po_resolved
        if field.value is None or field.status == "not_found":
            if optional:
                evidence.append(
                    f"Optional field absent: {label} — PO match ({match_status}) is authoritative"
                )
                continue
            reason_codes.append(code)
            evidence.append(f"Extraction missing: {label}")
            blocking_flags += 1
        elif field.status == "uncertain":
            if optional:
                evidence.append(
                    f"Optional field uncertain: {label} — does not block validation after PO match"
                )
                continue
            reason_codes.append(f"{code}_uncertain")
            evidence.append(f"Extraction uncertain: {label}")
            blocking_flags += 1

    if evidence_profile and evidence_profile.reconciliation_status == "residual_review":
        reason_codes.append("reconciliation_residual")
        evidence.append("Arithmetic reconciliation has unexplained residual")
        blocking_flags += 1

    if blocking_flags == 0:
        status = "PASS"
        reason_code = "EXTRACTION_OK"
    elif blocking_flags >= 2:
        status = "FLAG"
        reason_code = "EXTRACTION_FIELDS_INCOMPLETE"
    else:
        status = "FLAG"
        reason_code = reason_codes[0].upper()

    check = ValidationCheck(
        check_id="extraction_completeness",
        status=status,
        reason_code=reason_code,
        evidence=evidence or ["Required extraction fields present for validation"],
    )
    return check, reason_codes
