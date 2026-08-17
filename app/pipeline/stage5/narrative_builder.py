"""
InvoiceFlow AI — Stage 5: Deterministic Narrative Builder

Builds human-readable explanation narrative from Stage 4 rule trace.
Every narrative line traces back to a rule_id — no LLM in the source-of-truth path.

PRD Section 10: reason_code → approved language template → narrative line
"""

import logging
from typing import Any

from app.models.decision import DecisionRecord, RuleEvaluation
from app.models.explanation import NarrativeEntry

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# Narrative Templates by Decision Substate
# ═══════════════════════════════════════════════════════════

SUBSTATE_TEMPLATES = {
    "AUTO_APPROVED": "Invoice auto-approved: all validation controls passed. Amount within auto-approval limit.",
    "APPROVAL_REQUIRED": "Invoice requires manual approval before payment can proceed.",
    "STANDARD_REVIEW": "Invoice requires standard review by AP exception team.",
    "HIGH_PRIORITY_REVIEW": "Invoice requires high-priority review by senior finance.",
    "FRAUD_REVIEW": "Invoice flagged for fraud review by security team.",
    "VENDOR_SECURITY_REVIEW": "Invoice requires vendor security review due to bank detail changes.",
    "POLICY_EXCEPTION_REVIEW": "Invoice requires policy exception review.",
    "TERMINAL_REJECT": "Invoice rejected — terminal validation failure.",
    "WAITING_FOR_GRN": "Invoice processing paused: awaiting Goods Receipt Note.",
    "WAITING_FOR_REQUIRED_DATA": "Invoice processing paused: awaiting required data.",
    "REVALIDATION_REQUIRED": "Invoice requires revalidation: Stage 3 report is stale.",
    "POLICY_CONFIGURATION_ERROR": "Invoice processing paused: no applicable policy found.",
}

MATCH_STATUS_LABELS = {
    "matched": "PO matched on explicit reference",
    "high_confidence_match": "PO matched with high confidence (vendor + amount/lines)",
    "partial_match": "PO partially matched — some line variance",
    "ambiguous_match": "Multiple PO candidates — human must choose",
    "unmatched": "No PO match found in master data",
    "waiting_for_po": "Awaiting PO in master data",
    "waiting_for_grn": "Matched PO but goods receipt not yet posted",
}

REASON_CODE_EXPLANATIONS = {
    "missing_invoice_number": (
        "No invoice number on the document. This is acceptable when a PO match "
        "already identifies the payable."
    ),
    "missing_invoice_date": (
        "No invoice date on the document. Payment timing uses PO terms instead."
    ),
    "missing_currency": "Currency could not be determined — blocks automatic payment.",
    "EXTRACTION_FIELDS_INCOMPLETE": (
        "Required payment fields are missing or uncertain on the extraction."
    ),
    "reconciliation_residual": (
        "Line items and totals do not fully reconcile — unexplained difference remains."
    ),
    "AMBIGUOUS_PO_MATCH": (
        "More than one PO fits this invoice — a person must confirm which PO to pay against."
    ),
    "PRICE_VARIANCE_EXCEEDED": "Invoice price differs from the PO beyond allowed tolerance.",
    "BUDGET_EXCEEDED": "Invoice amount exceeds remaining PO budget.",
    "TAX_VARIANCE": "Tax amount differs from expected PO tax.",
    "GRN_MISSING": "Goods receipt note required before payment can proceed.",
    "DUPLICATE_CONFIRMED": "This invoice appears to be a duplicate of one already paid.",
    "VENDOR_BLACKLISTED": "Vendor is blocked — payment cannot proceed.",
    "VENDOR_INELIGIBLE": "Vendor is not eligible for payment under current policy.",
    "UNKNOWN_VALIDATION_STATE": "Validation ended in an unexpected state — routed to review.",
    "NO_APPLICABLE_POLICY": "No payment policy applies — configuration review needed.",
}

# Rule ID → narrative template
RULE_TEMPLATES = {
    "CONTRACT_GATE": "✅ Contract gate: Stage 4 input contract validated.",
    "CONTRACT_SCHEMA": "❌ Contract gate: {detail}",
    "CONTRACT_PROCESSING_STATE": "⏳ Contract gate: {detail}",
    "CONTRACT_FRESHNESS": "⏰ Freshness gate: {detail}",
    "HARD_CONTROL_BLOCKED": "🚫 Hard control: {detail}",
    "HARD_CONTROL_BLOCK_ACTIVE": "🚫 Hard control: {detail}",
    "HARD_CONTROL_TERMINAL_CODE": "🚫 Hard control: {detail}",
    "HARD_CONTROL_GATE": "✅ Hard control gate: no terminal controls.",
    "BANK_CHANGE_OVERRIDE": "🔒 Override: {detail}",
    "NEW_VENDOR_OVERRIDE": "⚠️ Override: {detail}",
    "CLUSTERING_OVERRIDE": "⚠️ Override: {detail}",
    "HIGH_FRAUD_OVERRIDE": "🚨 Override: {detail}",
    "STAGE3_STATE": "📋 Stage 3 validation: {detail}",
    "POLICY_NO_MATCH": "❌ Policy: {detail}",
    "VENDOR_RISK": "⚠️ Vendor risk: {detail}",
    "AUTHORITY_AUTO_APPROVE": "✅ Authority: {detail}",
}


def build_buyer_summary(
    decision_record: DecisionRecord,
    match_package: dict[str, Any] | None = None,
) -> str:
    """Plain-English one-liner for AP managers."""
    decision = decision_record.decision
    substate = decision_record.decision_substate
    po = _matched_po_label(match_package, decision_record)
    po_clause = f" against {po}" if po else ""

    templates = {
        "APPROVE": f"This invoice can be paid{po_clause}.",
        "REVIEW_REQUIRED": (
            f"This invoice matched a PO{po_clause} but needs a person to review before payment."
            if po
            else "This invoice needs a person to review before we pay."
        ),
        "REJECT": "Do not pay this invoice — a blocking rule failed.",
        "WAITING_FOR_VALIDATION": "We are waiting for more information before deciding.",
    }
    base = templates.get(decision, f"Decision: {decision}.")
    detail = SUBSTATE_TEMPLATES.get(substate, substate.replace("_", " ").title())
    if substate == "AUTO_APPROVED":
        return f"{base} All checks passed within auto-approval limits."
    if substate == "APPROVAL_REQUIRED":
        return f"{base} A manager must approve because of amount or policy limits."
    return f"{base} {detail}"


def build_narrative(
    decision_record: DecisionRecord,
    *,
    extraction: dict[str, Any] | None = None,
    match_package: dict[str, Any] | None = None,
    validation_report: dict[str, Any] | None = None,
    verification: dict[str, Any] | None = None,
    reconciliation: dict[str, Any] | None = None,
    routing_status: str | None = None,
    evidence_summary: list[str] | None = None,
) -> list[NarrativeEntry]:
    """
    Build deterministic explanation narrative from Stage 4 rule trace.

    Every line traces to a specific rule. No LLM generation.
    """
    entries: list[NarrativeEntry] = []
    step = 1
    summary_lines = evidence_summary or list(decision_record.evidence_summary)

    # --- Step 0: Buyer-facing summary ---
    entries.append(NarrativeEntry(
        step=step,
        category="buyer_summary",
        text=build_buyer_summary(decision_record, match_package),
        source_rule_id="BUYER_SUMMARY",
        icon=_decision_icon(decision_record.decision),
    ))
    step += 1

    # --- Stage 1: What we extracted from the document ---
    for entry in _build_stage1_entries(extraction, verification, reconciliation, routing_status):
        entry.step = step
        entries.append(entry)
        step += 1

    # --- PO match context (Stage 2) ---
    match_text = _describe_po_match(match_package, summary_lines)
    if match_text:
        entries.append(NarrativeEntry(
            step=step,
            category="po_match",
            text=match_text,
            source_rule_id="STAGE2_MATCH",
            icon="🔗",
        ))
        step += 1

    # --- Validation outcome (Stage 3) ---
    validation_text = _describe_validation(validation_report, summary_lines)
    if validation_text:
        entries.append(NarrativeEntry(
            step=step,
            category="validation",
            text=validation_text,
            source_rule_id="STAGE3_VALIDATION",
            icon="📋",
        ))
        step += 1

    # --- Decision summary ---
    substate = decision_record.decision_substate
    summary = SUBSTATE_TEMPLATES.get(substate, f"Decision: {decision_record.decision}/{substate}")
    entries.append(NarrativeEntry(
        step=step,
        category="decision_summary",
        text=summary,
        source_rule_id="DECISION_SUMMARY",
        icon=_decision_icon(decision_record.decision),
    ))
    step += 1

    # --- Human-readable reason codes ---
    if decision_record.reason_codes:
        for code in decision_record.reason_codes:
            explanation = REASON_CODE_EXPLANATIONS.get(
                code,
                code.replace("_", " ").capitalize(),
            )
            entries.append(NarrativeEntry(
                step=step,
                category="reason_explanation",
                text=f"Why flagged: {explanation}",
                source_rule_id=f"REASON_{code}",
                icon="💡",
            ))
            step += 1

    # --- Rule trace narrative ---
    for rule in decision_record.trace.rules_evaluated:
        text = _render_rule(rule)
        if text:
            entries.append(NarrativeEntry(
                step=step,
                category="rule_evaluation",
                text=text,
                source_rule_id=rule.rule_id,
                icon=_rule_icon(rule.result),
            ))
            step += 1

    # --- Policy summary ---
    policy = decision_record.trace.policy
    if policy.policy_id:
        entries.append(NarrativeEntry(
            step=step,
            category="policy",
            text=(
                f"Payment policy {policy.policy_id} (v{policy.policy_version}): "
                f"amount tier {policy.materiality_tier}, "
                f"{'eligible for auto-approve' if policy.auto_approve_eligible else 'requires approver'}"
            ),
            source_rule_id="POLICY_SUMMARY",
            icon="📋",
        ))
        step += 1

    # --- Authority summary ---
    authority = decision_record.trace.authority
    if authority.required:
        entries.append(NarrativeEntry(
            step=step,
            category="authority",
            text=(
                f"Approval required from {authority.approver_group} "
                f"(limit ${authority.required_limit:,.2f}"
                + (", dual-control required" if authority.dual_control_required else "")
                + ")"
            ),
            source_rule_id="AUTHORITY_SUMMARY",
            icon="👤",
        ))
        step += 1

    # --- Routing summary ---
    routing = decision_record.trace.routing
    if routing.target:
        entries.append(NarrativeEntry(
            step=step,
            category="routing",
            text=(
                f"Routed to {routing.target.replace('-', ' ')} — "
                f"priority {routing.priority}, respond within {routing.sla_hours}h"
            ),
            source_rule_id="ROUTING_SUMMARY",
            icon="📤",
        ))
        step += 1

    # --- Evidence trail (condensed) ---
    if summary_lines:
        condensed = [line for line in summary_lines if line.strip()][:8]
        if condensed:
            entries.append(NarrativeEntry(
                step=step,
                category="evidence_trail",
                text="Evidence trail: " + " | ".join(condensed),
                source_rule_id="EVIDENCE_TRAIL",
                icon="📎",
            ))
            step += 1

    logger.info(f"[{decision_record.invoice_id}] Narrative: {len(entries)} entries")
    return entries


def _matched_po_label(
    match_package: dict[str, Any] | None,
    decision_record: DecisionRecord,
) -> str | None:
    if match_package:
        selected = match_package.get("matched_pos") or match_package.get("selected_pos") or []
        if selected:
            first = selected[0]
            if isinstance(first, dict):
                return first.get("po_number") or first.get("po_id")
            return str(first)
        po = match_package.get("matched_po_number") or match_package.get("po_number")
        if po:
            return str(po)
    for line in decision_record.evidence_summary:
        if "Matched PO:" in line:
            return line.split("Matched PO:", 1)[1].strip()
    return None


def _describe_po_match(
    match_package: dict[str, Any] | None,
    summary_lines: list[str],
) -> str:
    status = None
    po = None
    score = None
    method = None

    if match_package:
        status = match_package.get("match_status")
        selected = match_package.get("matched_pos") or match_package.get("selected_pos") or []
        if selected and isinstance(selected[0], dict):
            po = selected[0].get("po_number") or selected[0].get("po_id")
            score = selected[0].get("match_score") or selected[0].get("score")
            method = selected[0].get("match_method") or selected[0].get("retrieval_method")
        if not po:
            po = match_package.get("matched_po_number") or match_package.get("po_number")

    for line in summary_lines:
        if line.startswith("Stage 2 match:"):
            status = status or line.split(":", 1)[1].strip()
        if line.startswith("Matched PO:"):
            po = po or line.split(":", 1)[1].strip()

    if not status and not po:
        return ""

    status_label = MATCH_STATUS_LABELS.get(status or "", status or "unknown")
    parts = [f"Purchase order match: {status_label}"]
    if po:
        parts.append(f"PO {po}")
    score_num = _safe_number(score)
    if score_num is not None:
        parts.append(f"score {score_num:.0f}")
    if method:
        parts.append(f"via {method.replace('_', ' ')}")
    return ". ".join(parts) + "."


def _describe_validation(
    validation_report: dict[str, Any] | None,
    summary_lines: list[str],
) -> str:
    state = None
    checks: dict[str, Any] = {}

    if validation_report:
        state = validation_report.get("overall_state")
        checks = validation_report.get("checks") or {}

    for line in summary_lines:
        for token in ("VALIDATED", "REVIEW_REQUIRED", "HOLD", "BLOCKED", "VALIDATION_INCOMPLETE"):
            if token in line:
                state = state or token
                break

    if not state and not checks:
        return ""

    parts = [f"Validation result: {state or 'completed'}"]
    failed = []
    flagged = []
    for check_id, check in checks.items():
        if not isinstance(check, dict):
            continue
        status = check.get("status")
        if status == "FAIL":
            failed.append(check_id.replace("_", " "))
        elif status == "FLAG":
            flagged.append(check_id.replace("_", " "))

    if failed:
        parts.append(f"failed checks: {', '.join(failed)}")
    elif flagged:
        parts.append(f"review flags: {', '.join(flagged)}")
    elif state == "VALIDATED":
        parts.append("all applicable controls passed")

    return ". ".join(parts) + "."


def _render_rule(rule: RuleEvaluation) -> str:
    """Render a rule evaluation into a narrative line."""
    template = RULE_TEMPLATES.get(rule.rule_id)
    if template and "{detail}" in template:
        return template.format(detail=rule.detail)
    if template:
        return template

    if rule.rule_id.startswith("MATERIALITY_"):
        return f"📊 Materiality: {rule.detail}"

    if rule.rule_id.startswith("AUTHORITY_"):
        return f"👤 Authority: {rule.detail}"

    if rule.result == "TRIGGERED":
        return f"⚡ {rule.rule_id}: {rule.detail}"
    if rule.result == "NOT_TRIGGERED":
        return f"✅ {rule.rule_id}: {rule.detail}"
    if rule.result == "ERROR":
        return f"❌ {rule.rule_id}: {rule.detail}"

    return ""


def build_narrative_from_artifacts(
    document_id: str,
    *,
    extraction: dict[str, Any] | None = None,
    match_package: dict[str, Any] | None = None,
    validation_report: dict[str, Any] | None = None,
    decision_record: DecisionRecord | dict[str, Any] | None = None,
    verification: dict[str, Any] | None = None,
    reconciliation: dict[str, Any] | None = None,
    routing_status: str | None = None,
) -> list[NarrativeEntry]:
    """Rebuild narrative from stored pipeline artifacts (e.g. after stage5_error)."""
    if decision_record is None:
        return [
            NarrativeEntry(
                step=1,
                category="buyer_summary",
                text=f"No payment decision recorded yet for invoice {document_id}.",
                source_rule_id="NO_DECISION",
                icon="⏳",
            )
        ]

    if isinstance(decision_record, dict):
        from app.models.decision import DecisionRecord as DR

        decision_record = DR.model_validate(decision_record)

    evidence_summary: list[str] = list(decision_record.evidence_summary or [])
    if validation_report and validation_report.get("evidence_summary"):
        evidence_summary = list(validation_report["evidence_summary"])

    return build_narrative(
        decision_record,
        extraction=extraction,
        match_package=match_package,
        validation_report=validation_report,
        verification=verification,
        reconciliation=reconciliation,
        routing_status=routing_status,
        evidence_summary=evidence_summary,
    )


def _safe_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _field_display(extraction: dict[str, Any] | None, field_name: str) -> str | None:
    if not extraction:
        return None
    field = extraction.get(field_name)
    if not isinstance(field, dict):
        return None
    val = field.get("value")
    status = field.get("status", "")
    if val is None or status == "not_found":
        return None
    conf = _safe_number(field.get("confidence"))
    conf_txt = f" ({conf:.0%} confidence)" if conf is not None else ""
    return f"{val}{conf_txt}"


def _build_stage1_entries(
    extraction: dict[str, Any] | None,
    verification: dict[str, Any] | None,
    reconciliation: dict[str, Any] | None,
    routing_status: str | None,
) -> list[NarrativeEntry]:
    """Human-readable Stage 1 extraction + verification summary."""
    entries: list[NarrativeEntry] = []
    if not extraction:
        return entries

    parts: list[str] = []
    for label, key in (
        ("Vendor", "vendor_name"),
        ("Invoice #", "invoice_number"),
        ("Invoice date", "invoice_date"),
        ("PO / reference", "po_reference"),
        ("Currency", "currency"),
        ("Total", "total_amount"),
    ):
        display = _field_display(extraction, key)
        if display:
            parts.append(f"{label}: {display}")
        else:
            parts.append(f"{label}: not on document")

    line_items = extraction.get("line_items") or []
    if line_items:
        parts.append(f"Line items: {len(line_items)} extracted")

    text = "Stage 1 extraction — " + "; ".join(parts) + "."
    entries.append(NarrativeEntry(
        step=0,
        category="stage1_extraction",
        text=text,
        source_rule_id="STAGE1_EXTRACTION",
        icon="📄",
    ))

    if verification:
        v_status = verification.get("verification_status", "unknown")
        v_conf = _safe_number(verification.get("overall_confidence"))
        v_text = f"Stage 1 verification — status {v_status}"
        if v_conf is not None:
            v_text += f" ({v_conf:.0%} overall confidence)"
        issues = verification.get("issues") or []
        actionable = [
            i for i in issues
            if isinstance(i, dict) and i.get("severity") in ("high", "medium")
        ]
        if actionable:
            v_text += ". Flags: " + "; ".join(
                f"{i.get('field')}: {i.get('reason')}" for i in actionable[:3]
            )
        entries.append(NarrativeEntry(
            step=0,
            category="stage1_verification",
            text=v_text + ".",
            source_rule_id="STAGE1_VERIFICATION",
            icon="🔍",
        ))

    if reconciliation:
        r_status = reconciliation.get("overall_status", "unknown")
        residual = _safe_number(reconciliation.get("residual_amount"))
        r_text = f"Stage 1 reconciliation — {r_status}"
        if residual is not None and abs(residual) > 0.01:
            r_text += f" (residual ${residual:,.2f})"
        entries.append(NarrativeEntry(
            step=0,
            category="stage1_reconciliation",
            text=r_text + ".",
            source_rule_id="STAGE1_RECONCILIATION",
            icon="🧮",
        ))

    if routing_status:
        entries.append(NarrativeEntry(
            step=0,
            category="stage1_routing",
            text=f"Stage 1 routing decision: {routing_status.replace('_', ' ')}.",
            source_rule_id="STAGE1_ROUTING",
            icon="🚦",
        ))

    return entries


def _decision_icon(decision: str) -> str:
    """Get icon for decision type."""
    return {
        "APPROVE": "✅",
        "REVIEW_REQUIRED": "⚠️",
        "REJECT": "🚫",
        "WAITING_FOR_VALIDATION": "⏳",
    }.get(decision, "❓")


def _rule_icon(result: str) -> str:
    """Get icon for rule result."""
    return {
        "TRIGGERED": "⚡",
        "NOT_TRIGGERED": "✅",
        "NOT_APPLICABLE": "➖",
        "ERROR": "❌",
    }.get(result, "")
