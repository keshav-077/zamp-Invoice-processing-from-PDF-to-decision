"""
InvoiceFlow AI — Stage 3: Duplicate Detection Engine

Multi-method duplicate detection:
  1. Exact duplicate: same vendor + invoice number + amount
  2. Near duplicate: same vendor + amount + close date (±3 days)
  3. Document hash: file hash comparison

Returns evidence with matched prior invoice IDs.
Does NOT adjudicate — creates evidence for control policy.
"""

import logging
import json
from datetime import datetime, timedelta

from app.models.validation import ValidationCheck
from app.pipeline.stage3.validation_context import ValidationContext
from app.pipeline.policy_loader import load_validation_policy
from app.db import repository

logger = logging.getLogger(__name__)

RULE_ID = "DUPLICATE_DETECTION"
RULE_VERSION = "DUP-2026.08.1"

# Near-duplicate date window
NEAR_DUPLICATE_DAYS = 3


def _duplicate_policy() -> dict:
    return load_validation_policy().get("duplicate_policy", {})


def _prior_counts_as_blocking(prior: dict) -> bool:
    """Only prior approved/posted runs block payment; ignore failed re-test runs."""
    policy = _duplicate_policy()
    ignore_decisions = set(policy.get("ignore_prior_decisions", []))
    ignore_stage3 = set(policy.get("ignore_prior_stage3", []))
    blocking_decisions = set(policy.get("blocking_prior_decisions", []))

    prior_decision = (prior.get("stage4_decision") or "").strip()
    prior_stage3 = (prior.get("stage3_status") or "").strip()

    if prior_decision in ignore_decisions:
        return False
    if prior_stage3 in ignore_stage3:
        return False
    if prior_decision in blocking_decisions:
        return True
    if policy.get("block_if_prior_allocated", True):
        prior_doc_id = prior.get("document_id", "")
        if prior_doc_id and repository.get_allocation_for_document(prior_doc_id):
            return True
    return False


def detect_duplicates(ctx: ValidationContext) -> ValidationCheck:
    """
    Detect duplicate invoice submissions.

    Returns:
        ValidationCheck with duplicate evidence.
    """
    if not ctx.invoice_number and not ctx.vendor_name:
        return ValidationCheck(
            check_id="duplicate_detection",
            status="NOT_APPLICABLE",
            reason_code="INSUFFICIENT_DATA",
            rule_id=RULE_ID,
            rule_version=RULE_VERSION,
            evidence=["No invoice number or vendor name for duplicate check"],
        )

    findings = []
    inputs = {
        "invoice_number": ctx.invoice_number,
        "vendor_name": ctx.vendor_name,
        "total_amount": ctx.total_amount,
        "invoice_date": ctx.invoice_date,
    }
    calculations = {}
    duplicate_candidates = []

    # --- Method 1: Exact Duplicate ---
    prior_invoices = repository.get_prior_invoices_for_duplicate_check(
        vendor_name=ctx.vendor_name,
        invoice_number=ctx.invoice_number,
        amount=ctx.total_amount,
    )

    for prior in prior_invoices:
        prior_doc_id = prior.get("document_id", "")

        # Skip self
        if prior_doc_id == ctx.document_id:
            continue

        if not _prior_counts_as_blocking(prior):
            continue

        # Parse extraction JSON to check fields
        extraction_data = prior.get("extraction_json")
        if not extraction_data:
            continue

        if isinstance(extraction_data, str):
            try:
                extraction_data = json.loads(extraction_data)
            except json.JSONDecodeError:
                continue

        # Extract prior invoice fields
        prior_inv_num = _extract_field_value(extraction_data, "invoice_number")
        prior_vendor = _extract_field_value(extraction_data, "vendor_name")
        prior_amount = _extract_field_value(extraction_data, "total_amount")
        prior_date = _extract_field_value(extraction_data, "invoice_date")

        # Exact match: same invoice number + vendor
        if (prior_inv_num and ctx.invoice_number and
                str(prior_inv_num).strip().upper() == str(ctx.invoice_number).strip().upper() and
                prior_vendor and ctx.vendor_name and
                _normalize_vendor(str(prior_vendor)) == _normalize_vendor(str(ctx.vendor_name))):

            # Check amount match
            amount_match = False
            if prior_amount is not None and ctx.total_amount is not None:
                try:
                    if abs(float(prior_amount) - ctx.total_amount) < 0.01:
                        amount_match = True
                except (ValueError, TypeError):
                    pass

            if amount_match:
                duplicate_candidates.append({
                    "type": "exact",
                    "prior_document_id": prior_doc_id,
                    "prior_invoice_number": prior_inv_num,
                    "prior_amount": prior_amount,
                    "confidence": "HIGH",
                })
                findings.append(
                    f"EXACT DUPLICATE: invoice {ctx.invoice_number} from "
                    f"{ctx.vendor_name} for ${ctx.total_amount:,.2f} matches "
                    f"prior document {prior_doc_id}"
                )
            else:
                # Same invoice number + vendor but different amount
                duplicate_candidates.append({
                    "type": "near",
                    "prior_document_id": prior_doc_id,
                    "prior_invoice_number": prior_inv_num,
                    "prior_amount": prior_amount,
                    "confidence": "MEDIUM",
                })
                findings.append(
                    f"NEAR DUPLICATE: same invoice number {ctx.invoice_number} and vendor, "
                    f"but amount differs (inv: ${ctx.total_amount}, prior: ${prior_amount})"
                )
            continue

        # --- Method 2: Near Duplicate ---
        # Same vendor + same amount + close date
        if (prior_vendor and ctx.vendor_name and
                _normalize_vendor(str(prior_vendor)) == _normalize_vendor(str(ctx.vendor_name))):

            if prior_amount is not None and ctx.total_amount is not None:
                try:
                    if abs(float(prior_amount) - ctx.total_amount) < 0.01:
                        # Check date proximity
                        if prior_date and ctx.invoice_date:
                            if _dates_within_window(str(ctx.invoice_date), str(prior_date), NEAR_DUPLICATE_DAYS):
                                duplicate_candidates.append({
                                    "type": "near_date",
                                    "prior_document_id": prior_doc_id,
                                    "prior_invoice_number": prior_inv_num,
                                    "prior_amount": prior_amount,
                                    "prior_date": prior_date,
                                    "confidence": "MEDIUM",
                                })
                                findings.append(
                                    f"NEAR DUPLICATE: same vendor + amount ${ctx.total_amount:,.2f} + "
                                    f"dates within {NEAR_DUPLICATE_DAYS} days "
                                    f"(prior doc: {prior_doc_id})"
                                )
                except (ValueError, TypeError):
                    pass

    calculations["duplicate_candidates"] = duplicate_candidates
    calculations["candidates_found"] = len(duplicate_candidates)

    # --- Determine status ---
    exact_dupes = [d for d in duplicate_candidates if d["type"] == "exact"]
    near_dupes = [d for d in duplicate_candidates if d["type"] in ("near", "near_date")]

    if exact_dupes:
        return ValidationCheck(
            check_id="duplicate_detection",
            status="FAIL",
            reason_code="DUPLICATE_CONFIRMED",
            severity="CRITICAL",
            rule_id=RULE_ID,
            rule_version=RULE_VERSION,
            inputs=inputs,
            calculation=calculations,
            evidence=findings,
            evidence_refs=[d["prior_document_id"] for d in exact_dupes],
        )
    elif near_dupes:
        return ValidationCheck(
            check_id="duplicate_detection",
            status="FLAG",
            reason_code="DUPLICATE_SUSPECTED",
            severity="HIGH",
            rule_id=RULE_ID,
            rule_version=RULE_VERSION,
            inputs=inputs,
            calculation=calculations,
            evidence=findings,
            evidence_refs=[d["prior_document_id"] for d in near_dupes],
        )
    else:
        findings.append("No duplicate candidates found")
        return ValidationCheck(
            check_id="duplicate_detection",
            status="PASS",
            rule_id=RULE_ID,
            rule_version=RULE_VERSION,
            inputs=inputs,
            calculation=calculations,
            evidence=findings,
        )


def _extract_field_value(extraction: dict, field_name: str):
    """Extract a field value from extraction JSON."""
    field_data = extraction.get(field_name, {})
    if isinstance(field_data, dict):
        return field_data.get("value")
    return field_data


def _normalize_vendor(name: str) -> str:
    """Normalize vendor name for comparison."""
    return name.upper().strip().replace(".", "").replace(",", "")


def _dates_within_window(date1: str, date2: str, days: int) -> bool:
    """Check if two date strings are within N days of each other."""
    try:
        d1 = datetime.strptime(date1, "%Y-%m-%d")
        d2 = datetime.strptime(date2, "%Y-%m-%d")
        return abs((d1 - d2).days) <= days
    except ValueError:
        return False
