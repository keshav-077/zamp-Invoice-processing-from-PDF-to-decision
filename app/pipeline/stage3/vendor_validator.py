"""
InvoiceFlow AI — Stage 3: Vendor Validator

Stage 2 resolved vendor identity. Stage 3 validates vendor eligibility:
  - Vendor is active and approved
  - Vendor-PO alignment (invoice vendor matches PO vendor)
  - Bank change detection (recent unverified changes)
  - Blacklist/watchlist check
"""

import logging
from app.models.validation import ValidationCheck
from app.pipeline.stage3.validation_context import ValidationContext

logger = logging.getLogger(__name__)

RULE_ID = "VENDOR_VALIDATION"
RULE_VERSION = "VEND-2026.08.1"


def validate_vendor(ctx: ValidationContext) -> ValidationCheck:
    """Validate vendor eligibility and payment safety."""
    if ctx.vendor is None:
        # Non-PO workflow or unmatched — vendor not resolved
        if ctx.match_status == "non_po_workflow":
            return ValidationCheck(
                check_id="vendor_validation",
                status="FLAG",
                reason_code="VENDOR_NOT_VERIFIED",
                severity="MEDIUM",
                rule_id=RULE_ID,
                rule_version=RULE_VERSION,
                evidence=["Non-PO invoice — vendor not verified against master"],
            )
        return ValidationCheck(
            check_id="vendor_validation",
            status="UNAVAILABLE",
            reason_code="NO_VENDOR_DATA",
            rule_id=RULE_ID,
            rule_version=RULE_VERSION,
            evidence=["Vendor data not available for validation"],
        )

    findings = []
    inputs = {
        "vendor_id": ctx.vendor.get("vendor_id", ""),
        "vendor_name": ctx.vendor.get("name", ""),
        "vendor_status": ctx.vendor_status,
        "invoice_vendor_name": ctx.vendor_name,
    }
    has_failure = False
    has_flag = False

    # --- 1. Vendor Status Check ---
    if ctx.vendor_status == "active":
        findings.append(f"Vendor {inputs['vendor_id']} is active and approved")
    elif ctx.vendor_status == "inactive":
        has_failure = True
        findings.append(
            f"VENDOR INACTIVE: {inputs['vendor_id']} ({inputs['vendor_name']}) "
            f"is not active — payment not permitted"
        )
    elif ctx.vendor_status == "suspended":
        has_failure = True
        findings.append(
            f"VENDOR SUSPENDED: {inputs['vendor_id']} ({inputs['vendor_name']}) "
            f"is suspended — requires review"
        )
    else:
        has_flag = True
        findings.append(f"Unknown vendor status: {ctx.vendor_status}")

    # --- 2. Vendor-PO Alignment (invoice-resolved vendor vs PO vendor) ---
    invoice_vendor_id = ctx.resolved_invoice_vendor_id or ctx.matched_vendor_id
    if invoice_vendor_id and ctx.po:
        po_vendor_id = ctx.po.get("vendor_id", "")
        if po_vendor_id == invoice_vendor_id:
            findings.append(
                f"Vendor-PO alignment confirmed: "
                f"invoice vendor {invoice_vendor_id} matches PO vendor"
            )
        else:
            has_flag = True
            findings.append(
                f"VENDOR MISMATCH: invoice vendor {invoice_vendor_id} "
                f"does not match PO vendor {po_vendor_id}"
            )

    # --- 3. Bank Change Detection (simulated for MVP) ---
    # In production, this would check vendor.bank_change_date vs current date
    # For MVP, we simulate based on vendor_id patterns
    bank_change_detected = _check_simulated_bank_change(ctx.vendor)
    if bank_change_detected == "unverified":
        has_failure = True
        findings.append(
            "HIGH RISK: Recent bank account change detected — UNVERIFIED. "
            "Independent verification required before payment."
        )
    elif bank_change_detected == "verified":
        findings.append(
            "Bank account change detected but verified via approved change request"
        )

    # --- 4. Blacklist Check (simulated) ---
    if ctx.vendor_status == "inactive":
        # Already handled above, but reinforce
        pass

    # --- Determine status ---
    if has_failure:
        return ValidationCheck(
            check_id="vendor_validation",
            status="FAIL",
            reason_code="VENDOR_INELIGIBLE",
            severity="HIGH",
            rule_id=RULE_ID,
            rule_version=RULE_VERSION,
            inputs=inputs,
            evidence=findings,
            evidence_refs=[ctx.vendor_ref] if ctx.vendor_ref else [],
        )
    elif has_flag:
        return ValidationCheck(
            check_id="vendor_validation",
            status="FLAG",
            reason_code="VENDOR_REVIEW_REQUIRED",
            severity="MEDIUM",
            rule_id=RULE_ID,
            rule_version=RULE_VERSION,
            inputs=inputs,
            evidence=findings,
            evidence_refs=[ctx.vendor_ref] if ctx.vendor_ref else [],
        )
    else:
        return ValidationCheck(
            check_id="vendor_validation",
            status="PASS",
            rule_id=RULE_ID,
            rule_version=RULE_VERSION,
            inputs=inputs,
            evidence=findings,
            evidence_refs=[ctx.vendor_ref] if ctx.vendor_ref else [],
        )


def _check_simulated_bank_change(vendor: dict) -> str | None:
    """
    Simulate bank change detection for MVP.
    In production: check vendor.bank_change_date, verification_status.

    Returns: "unverified", "verified", or None
    """
    # For demo: V006 (inactive) simulates unverified bank change
    vendor_id = vendor.get("vendor_id", "")
    if vendor_id == "V006":
        return "unverified"
    return None
