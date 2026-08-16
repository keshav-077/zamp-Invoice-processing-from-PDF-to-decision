"""
InvoiceFlow AI — Stage 3: Validation Context

Builds an immutable snapshot of all data needed for the 7 validation engines.
Each validator operates against this single context — no direct DB access.
"""

import logging
from dataclasses import dataclass, field

from app.db import repository
from app.models.extraction import InvoiceExtraction
from app.models.match import MatchPackage, POCandidate
from app.config import settings
from app.pipeline.policy_loader import load_validation_policy

logger = logging.getLogger(__name__)


@dataclass
class ValidationContext:
    """Immutable snapshot of all data needed for validation."""

    # --- Invoice (from Stage 1) ---
    document_id: str = ""
    invoice_number: str | None = None
    invoice_date: str | None = None
    vendor_name: str | None = None
    currency: str | None = None
    subtotal: float | None = None
    tax_amount: float | None = None
    total_amount: float | None = None
    invoice_lines: list[dict] = field(default_factory=list)

    # --- Match (from Stage 2) ---
    match_status: str = ""
    matched_po_number: str | None = None
    matched_vendor_id: str | None = None
    resolved_invoice_vendor_id: str | None = None
    match_confidence: float = 0.0
    line_mappings: list[dict] = field(default_factory=list)
    match_flags: list[str] = field(default_factory=list)

    # --- PO (from DB) ---
    po: dict | None = None
    po_lines: list[dict] = field(default_factory=list)
    po_total: float = 0.0
    po_remaining: float = 0.0
    po_previously_invoiced: float = 0.0
    po_status: str = ""
    po_type: str = "standard"
    po_currency: str = ""

    # --- Vendor (from DB) ---
    vendor: dict | None = None
    vendor_status: str = ""

    # --- GRN (from DB) ---
    grn_records: list[dict] = field(default_factory=list)
    has_grn: bool = False
    total_received_amount: float = 0.0

    # --- Policy ---
    price_tolerance_pct: float = 0.02  # 2%
    qty_tolerance_pct: float = 0.05  # 5%
    tax_tolerance_pct: float = 0.12  # 12% — overridden from settings in build_context
    budget_tolerance_pct: float = 0.05  # 5%
    expected_tax_rate: float = 0.08  # overridden from settings / invoice in build_context
    approval_thresholds: list[float] = field(
        default_factory=lambda: [10000, 25000, 50000]
    )

    # --- Source references ---
    stage1_ref: str = ""
    stage2_ref: str = ""
    po_ref: str = ""
    vendor_ref: str = ""
    grn_ref: str = ""


def build_context(
    document_id: str,
    extraction: InvoiceExtraction,
    match_package: MatchPackage,
) -> ValidationContext:
    """
    Build a complete validation context from Stage 1 extraction + Stage 2 match.

    Args:
        document_id: Invoice document ID
        extraction: Stage 1 extraction result
        match_package: Stage 2 match result

    Returns:
        ValidationContext with all data needed for 7 engines.
    """
    ctx = ValidationContext(document_id=document_id)

    # --- Extract invoice fields ---
    ctx.invoice_number = str(extraction.invoice_number.value) if extraction.invoice_number.value else None
    ctx.invoice_date = str(extraction.invoice_date.value) if extraction.invoice_date.value else None
    ctx.vendor_name = str(extraction.vendor_name.value) if extraction.vendor_name.value else None
    ctx.currency = str(extraction.currency.value) if extraction.currency.value else None
    ctx.subtotal = float(extraction.subtotal.value) if extraction.subtotal.value is not None else None
    ctx.tax_amount = float(extraction.tax_amount.value) if extraction.tax_amount.value is not None else None
    ctx.total_amount = float(extraction.total_amount.value) if extraction.total_amount.value is not None else None

    ctx.invoice_lines = [
        {
            "description": li.description,
            "quantity": li.quantity,
            "unit_price": li.unit_price,
            "amount": li.amount,
        }
        for li in extraction.line_items
    ]

    # --- Match context ---
    ctx.match_status = match_package.match_status
    ctx.match_flags = list(match_package.flags)
    resolved_invoice_vendor_id = match_package.resolved_invoice_vendor_id

    if match_package.matched_pos:
        top_candidate = match_package.matched_pos[0]
        ctx.matched_po_number = top_candidate.po_number
        ctx.matched_vendor_id = top_candidate.vendor_id
        ctx.match_confidence = top_candidate.score.total
        ctx.resolved_invoice_vendor_id = resolved_invoice_vendor_id

        ctx.line_mappings = [
            {
                "invoice_line": lm.invoice_line,
                "po_line": lm.po_line,
                "match_type": lm.match_type,
                "similarity_score": lm.similarity_score,
            }
            for lm in top_candidate.line_mappings
        ]

        # --- Load PO from DB ---
        po_data = repository.get_po(top_candidate.po_number)
        if po_data:
            ctx.po = po_data
            ctx.po_lines = po_data.get("lines", [])
            ctx.po_total = po_data.get("total_amount", 0)
            ctx.po_remaining = ctx.po_total - po_data.get("previously_invoiced", 0)
            ctx.po_previously_invoiced = po_data.get("previously_invoiced", 0)
            ctx.po_status = po_data.get("status", "")
            ctx.po_type = po_data.get("po_type", "standard")
            ctx.po_currency = po_data.get("currency", "")
            ctx.po_ref = f"{top_candidate.po_number}:v1"

        # --- Load Vendor from DB ---
        if top_candidate.vendor_id:
            vendor_data = repository.get_vendor_by_id(top_candidate.vendor_id)
            if vendor_data:
                ctx.vendor = vendor_data
                ctx.vendor_status = vendor_data.get("status", "")
                ctx.vendor_ref = f"{top_candidate.vendor_id}:v1"

        # --- Load GRN from DB ---
        grn_data = repository.get_grn_for_po(top_candidate.po_number)
        ctx.grn_records = grn_data
        ctx.has_grn = len(grn_data) > 0
        ctx.total_received_amount = sum(g.get("received_amount", 0) for g in grn_data)

    # --- Source refs ---
    ctx.stage1_ref = f"S1-{document_id}"
    ctx.stage2_ref = f"S2-{document_id}"

    # --- Policy from versioned config ---
    policy = load_validation_policy()
    tolerances = policy.get("tolerances", {})
    ctx.price_tolerance_pct = tolerances.get("price_tolerance_pct", 0.02)
    ctx.qty_tolerance_pct = tolerances.get("qty_tolerance_pct", 0.05)
    ctx.tax_tolerance_pct = tolerances.get("tax_tolerance_pct", settings.tax_tolerance_pct)
    ctx.budget_tolerance_pct = tolerances.get("budget_tolerance_pct", 0.05)
    ctx.approval_thresholds = policy.get("approval_thresholds", ctx.approval_thresholds)

    tax_policy = policy.get("tax_policy", {})
    tax_mode = tax_policy.get("mode", "expected_rate")
    default_rate = tax_policy.get("default_expected_rate", settings.expected_tax_rate)

    po_meta = (ctx.po or {}).get("metadata") or {}
    if po_meta.get("import_derived") and po_meta.get("tax_rate") is None:
        tax_mode = "consistency_only"

    if tax_mode == "zero_exempt":
        ctx.expected_tax_rate = 0.0
    elif tax_mode == "consistency_only":
        # Validate arithmetic consistency only — expected rate mirrors invoice when present
        if ctx.subtotal and ctx.tax_amount is not None and ctx.subtotal > 0:
            ctx.expected_tax_rate = ctx.tax_amount / ctx.subtotal
        else:
            ctx.expected_tax_rate = default_rate
    else:
        ctx.expected_tax_rate = default_rate

    vendor_rates = tax_policy.get("vendor_tax_rates", {})
    if ctx.vendor_name:
        vendor_key = ctx.vendor_name.lower().strip()
        if vendor_key in vendor_rates:
            ctx.expected_tax_rate = float(vendor_rates[vendor_key])

    logger.info(
        f"[{document_id}] Validation context built: "
        f"PO={ctx.matched_po_number}, vendor={ctx.matched_vendor_id}, "
        f"GRN={ctx.has_grn}, total={ctx.total_amount}"
    )
    return ctx
