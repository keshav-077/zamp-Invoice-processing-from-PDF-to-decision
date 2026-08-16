"""
InvoiceFlow AI — Stage 5: Deterministic Narrative Builder

Builds human-readable explanation narrative from Stage 4 rule trace.
Every narrative line traces back to a rule_id — no LLM in the source-of-truth path.

PRD Section 10: reason_code → approved language template → narrative line
"""

import logging
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
    "STAGE3_STATE": "📋 Stage 3 state: {detail}",
    "POLICY_NO_MATCH": "❌ Policy: {detail}",
    "VENDOR_RISK": "⚠️ Vendor risk: {detail}",
    "AUTHORITY_AUTO_APPROVE": "✅ Authority: {detail}",
}


def build_buyer_summary(decision_record: DecisionRecord) -> str:
    """Plain-English one-liner for AP managers (demo / interview)."""
    decision = decision_record.decision
    substate = decision_record.decision_substate
    templates = {
        "AUTO_APPROVED": "This invoice passed all checks and can be paid automatically.",
        "APPROVAL_REQUIRED": "This invoice matched the PO but needs a manager to approve payment.",
        "REVIEW_REQUIRED": "Something needs a person to look at this before we pay.",
        "REJECTED": "Do not pay this invoice — a blocking rule failed.",
        "WAITING_FOR_VALIDATION": "We are waiting for more information before deciding.",
    }
    base = templates.get(decision, f"Decision: {decision}.")
    return f"{base} ({substate.replace('_', ' ').title()})"


def build_narrative(decision_record: DecisionRecord) -> list[NarrativeEntry]:
    """
    Build deterministic explanation narrative from Stage 4 rule trace.

    Every line traces to a specific rule. No LLM generation.

    Args:
        decision_record: Stage 4 DecisionRecord with complete trace

    Returns:
        List of NarrativeEntry with ordered explanation steps.
    """
    entries: list[NarrativeEntry] = []
    step = 1

    # --- Step 0: Buyer-facing summary ---
    entries.append(NarrativeEntry(
        step=step,
        category="buyer_summary",
        text=build_buyer_summary(decision_record),
        source_rule_id="BUYER_SUMMARY",
        icon=_decision_icon(decision_record.decision),
    ))
    step += 1

    # --- Step 1: Decision summary ---
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

    # --- Step 2: Decision details ---
    entries.append(NarrativeEntry(
        step=step,
        category="decision_detail",
        text=f"Decision: {decision_record.decision} | Substate: {substate}",
        source_rule_id="DECISION_DETAIL",
    ))
    step += 1

    # --- Step 3-N: Rule trace narrative ---
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
                f"Policy: {policy.policy_id} v{policy.policy_version} | "
                f"Tier: {policy.materiality_tier} | "
                f"Auto-approve eligible: {policy.auto_approve_eligible}"
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
                f"Approval required: group={authority.approver_group}, "
                f"limit=${authority.required_limit:,.2f}"
                + (", dual-control required" if authority.dual_control_required else "")
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
                f"Routed to: {routing.target} | "
                f"Priority: {routing.priority} | SLA: {routing.sla_hours}h"
            ),
            source_rule_id="ROUTING_SUMMARY",
            icon="📤",
        ))
        step += 1

    # --- Reason codes ---
    if decision_record.reason_codes:
        entries.append(NarrativeEntry(
            step=step,
            category="reason_codes",
            text=f"Reason codes: {', '.join(decision_record.reason_codes)}",
            source_rule_id="REASON_CODES",
            icon="🏷️",
        ))
        step += 1

    logger.info(f"[{decision_record.invoice_id}] Narrative: {len(entries)} entries")
    return entries


def _render_rule(rule: RuleEvaluation) -> str:
    """Render a rule evaluation into a narrative line."""
    # Check if we have a template
    template = RULE_TEMPLATES.get(rule.rule_id)
    if template and "{detail}" in template:
        return template.format(detail=rule.detail)
    elif template:
        return template

    # Handle materiality rules
    if rule.rule_id.startswith("MATERIALITY_"):
        return f"📊 Materiality: {rule.detail}"

    # Handle authority rules
    if rule.rule_id.startswith("AUTHORITY_"):
        return f"👤 Authority: {rule.detail}"

    # Generic rendering for unknown rules
    if rule.result == "TRIGGERED":
        return f"⚡ {rule.rule_id}: {rule.detail}"
    elif rule.result == "NOT_TRIGGERED":
        return f"✅ {rule.rule_id}: {rule.detail}"
    elif rule.result == "ERROR":
        return f"❌ {rule.rule_id}: {rule.detail}"

    return ""


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
