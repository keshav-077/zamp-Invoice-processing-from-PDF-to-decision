"""
InvoiceFlow AI — Stage 4: Hard Control Gate

Step 2 of the 10-step decision pipeline.

Evaluates terminal controls that cannot be weakened:
  - Stage 3 BLOCKED → REJECT / TERMINAL_REJECT
  - Active BLOCK controls → REJECT
  - Confirmed security violations → REJECT

PRD invariant: "Stage 3 BLOCKED is not silently downgraded
because of amount or vendor trust."
"""

import logging
from dataclasses import dataclass

from app.models.decision import RuleEvaluation
from app.pipeline.stage4.decision_context import DecisionContext

logger = logging.getLogger(__name__)

# Reason codes that are terminal (cannot be weakened)
TERMINAL_REASON_CODES = {
    "DUPLICATE_CONFIRMED",
    "VENDOR_BLACKLISTED",
}


@dataclass
class HardControlResult:
    """Result of hard control evaluation."""
    triggered: bool
    decision: str | None = None
    substate: str | None = None
    reason_codes: list[str] | None = None
    rules: list[RuleEvaluation] | None = None


def evaluate_hard_controls(ctx: DecisionContext) -> HardControlResult:
    """
    Evaluate terminal hard controls.

    Returns:
        HardControlResult — if triggered=True, decision is REJECT (non-negotiable).
    """
    rules = []

    # --- Stage 3 BLOCKED → REJECT ---
    if ctx.validation_state == "BLOCKED":
        rule = RuleEvaluation(
            rule_id="HARD_CONTROL_BLOCKED",
            result="TRIGGERED",
            priority=1,
            detail=f"Stage 3 state BLOCKED: {', '.join(ctx.reason_codes)}",
            inputs={"validation_state": "BLOCKED", "reason_codes": ctx.reason_codes},
        )
        rules.append(rule)
        logger.info(f"[{ctx.invoice_id}] Hard control: BLOCKED → REJECT")
        return HardControlResult(
            triggered=True,
            decision="REJECT",
            substate="TERMINAL_REJECT",
            reason_codes=list(ctx.reason_codes),
            rules=rules,
        )

    # --- Active BLOCK controls ---
    block_controls = [c for c in ctx.controls if c.get("control_type") == "BLOCK"]
    if block_controls:
        block_reasons = [c.get("reason_code", "UNKNOWN") for c in block_controls]
        rule = RuleEvaluation(
            rule_id="HARD_CONTROL_BLOCK_ACTIVE",
            result="TRIGGERED",
            priority=1,
            detail=f"Active BLOCK controls: {', '.join(block_reasons)}",
            inputs={"block_controls": len(block_controls)},
        )
        rules.append(rule)
        logger.info(f"[{ctx.invoice_id}] Hard control: BLOCK controls → REJECT")
        return HardControlResult(
            triggered=True,
            decision="REJECT",
            substate="TERMINAL_REJECT",
            reason_codes=block_reasons,
            rules=rules,
        )

    # --- Terminal reason codes in findings ---
    terminal_found = [rc for rc in ctx.reason_codes if rc in TERMINAL_REASON_CODES]
    if terminal_found:
        rule = RuleEvaluation(
            rule_id="HARD_CONTROL_TERMINAL_CODE",
            result="TRIGGERED",
            priority=1,
            detail=f"Terminal reason codes: {', '.join(terminal_found)}",
            inputs={"terminal_codes": terminal_found},
        )
        rules.append(rule)
        logger.info(f"[{ctx.invoice_id}] Hard control: terminal code → REJECT")
        return HardControlResult(
            triggered=True,
            decision="REJECT",
            substate="TERMINAL_REJECT",
            reason_codes=terminal_found,
            rules=rules,
        )

    # --- Not triggered ---
    rule = RuleEvaluation(
        rule_id="HARD_CONTROL_GATE",
        result="NOT_TRIGGERED",
        priority=1,
        detail="No terminal hard controls",
    )
    rules.append(rule)
    return HardControlResult(triggered=False, rules=rules)
