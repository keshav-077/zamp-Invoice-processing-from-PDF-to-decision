"""
Build extraction evidence profile after verification and reconciliation.
"""

from __future__ import annotations

from app.models.evidence import EvidenceProfile
from app.models.extraction import InvoiceExtraction
from app.models.reconciliation import ReconciliationResult
from app.models.verification import VerificationResult
from app.pipeline.policy_loader import load_routing_policy


SIGNAL_FIELD_MAP = {
    "vendor_name": "vendor",
    "total_amount": "total",
    "po_reference": "po_reference",
    "line_items": "line_items",
    "typed_references": "typed_references",
    "currency": "currency",
    "invoice_number": "invoice_number",
    "invoice_date": "invoice_date",
}


def _field_usable(field_name: str, extraction: InvoiceExtraction) -> bool:
    if field_name == "line_items":
        return len(extraction.line_items) > 0
    if field_name == "typed_references":
        return any(
            ref.value and ref.status in ("extracted", "inferred")
            for ref in extraction.typed_references
        )
    field_map = {
        "vendor_name": extraction.vendor_name,
        "total_amount": extraction.total_amount,
        "po_reference": extraction.po_reference,
        "currency": extraction.currency,
        "invoice_number": extraction.invoice_number,
        "invoice_date": extraction.invoice_date,
    }
    field = field_map.get(field_name)
    if field is None:
        return False
    return field.value is not None and field.status not in ("not_found",)


def _field_uncertain(field_name: str, extraction: InvoiceExtraction) -> bool:
    if field_name == "line_items":
        return False
    if field_name == "typed_references":
        return False
    field_map = {
        "vendor_name": extraction.vendor_name,
        "total_amount": extraction.total_amount,
        "po_reference": extraction.po_reference,
        "currency": extraction.currency,
        "invoice_number": extraction.invoice_number,
        "invoice_date": extraction.invoice_date,
    }
    field = field_map.get(field_name)
    return field is not None and field.status == "uncertain"


def build_evidence_profile(
    extraction: InvoiceExtraction,
    verification: VerificationResult | None = None,
    reconciliation: ReconciliationResult | None = None,
    policy: dict | None = None,
) -> EvidenceProfile:
    """Compute evidence profile from extraction and optional verification/reconciliation."""
    policy = policy or load_routing_policy()
    po_resolution = policy.get("po_resolution", {})
    any_of = po_resolution.get("minimum_signals", {}).get("any_of")
    if not any_of:
        any_of = policy.get("matching_signals", ["vendor_name", "total_amount", "line_items"])

    approval_fields = policy.get(
        "approval_critical_fields",
        policy.get("critical_fields", []),
    )

    approval_labels = {
        SIGNAL_FIELD_MAP.get(f, f) for f in approval_fields
    }
    tracked = set(SIGNAL_FIELD_MAP.keys())
    available: list[str] = []
    missing: list[str] = []
    optional_missing: list[str] = []
    uncertain: list[str] = []
    matchable: list[str] = []

    for field_name in tracked:
        label = SIGNAL_FIELD_MAP.get(field_name, field_name)
        if _field_usable(field_name, extraction):
            available.append(label)
            if field_name in any_of:
                matchable.append(label)
        elif _field_uncertain(field_name, extraction):
            uncertain.append(label)
            if label in approval_labels:
                missing.append(label)
            else:
                optional_missing.append(label)
        else:
            if label in approval_labels:
                missing.append(label)
            else:
                optional_missing.append(label)

    critical_missing = []
    for field_name in approval_fields:
        label = SIGNAL_FIELD_MAP.get(field_name, field_name)
        if label not in available and label not in uncertain:
            critical_missing.append(label)
        elif label in uncertain:
            critical_missing.append(label)

    recon_status = reconciliation.overall_status if reconciliation else None

    return EvidenceProfile(
        available=available,
        missing=missing,
        optional_missing=optional_missing,
        uncertain=uncertain,
        critical_missing=critical_missing,
        matchable_signals=matchable,
        reconciliation_status=recon_status,
    )


def can_run_po_resolution(profile: EvidenceProfile, policy: dict | None = None) -> bool:
    """True when any matchable signal exists (Spec Section 7)."""
    policy = policy or load_routing_policy()
    po_resolution = policy.get("po_resolution", {})
    if not po_resolution.get("allow_partial_evidence", True):
        return len(profile.matchable_signals) == len(
            po_resolution.get("minimum_signals", {}).get("any_of", [])
        )
    return len(profile.matchable_signals) > 0
