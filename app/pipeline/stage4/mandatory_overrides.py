"""
InvoiceFlow AI — Stage 4: Mandatory Override Layer

Step 3 of the 10-step decision pipeline.

Overrides sit ABOVE normal materiality/automation logic.
A low amount or high confidence score CANNOT bypass these.

Overrides (PRD Section 10):
  1. Vendor bank-detail change (unverified)
  2. New vendor first payment
  3. Sub-threshold clustering (fraud signal)
  4. Confirmed security/compliance block
"""

import logging
from dataclasses import dataclass

from app.models.decision import RuleEvaluation
from app.pipeline.stage4.decision_context import DecisionContext

logger = logging.getLogger(__name__)


@dataclass
class OverrideResult:
    """Result of mandatory override evaluation."""
    triggered: bool
    decision: str | None = None
    substate: str | None = None
    reason_codes: list[str] | None = None
    rules: list[RuleEvaluation] | None = None


def evaluate_overrides(ctx: DecisionContext) -> OverrideResult:
    """
    Evaluate mandatory overrides that cannot be bypassed.

    Returns:
        OverrideResult — if triggered=True, decision is forced to REVIEW_REQUIRED.
    """
    rules = []
    triggered_reasons = []
    substate = "STANDARD_REVIEW"

    # --- 1. Vendor Bank Change (unverified) ---
    if ctx.bank_change_detected and not ctx.bank_change_verified:
        rule = RuleEvaluation(
            rule_id="BANK_CHANGE_OVERRIDE",
            result="TRIGGERED",
            priority=2,
            detail="Recent bank account change not independently verified",
            inputs={
                "bank_change_detected": True,
                "bank_change_verified": False,
            },
        )
        rules.append(rule)
        triggered_reasons.append("UNVERIFIED_BANK_CHANGE")
        substate = "VENDOR_SECURITY_REVIEW"
        logger.info(f"[{ctx.invoice_id}] Override: unverified bank change")
    else:
        rules.append(RuleEvaluation(
            rule_id="BANK_CHANGE_OVERRIDE",
            result="NOT_TRIGGERED",
            priority=2,
            detail="No unverified bank change",
        ))

    # --- 2. New Vendor First Payment ---
    if ctx.is_first_payment:
        new_vendor_threshold = 10000.0  # Policy configurable
        if ctx.amount is not None and ctx.amount > new_vendor_threshold:
            rule = RuleEvaluation(
                rule_id="NEW_VENDOR_OVERRIDE",
                result="TRIGGERED",
                priority=4,
                detail=(
                    f"First payment to new vendor {ctx.vendor_id} "
                    f"for ${ctx.amount:,.2f} (threshold: ${new_vendor_threshold:,.2f})"
                ),
                inputs={
                    "vendor_id": ctx.vendor_id,
                    "amount": ctx.amount,
                    "is_first_payment": True,
                    "threshold": new_vendor_threshold,
                },
            )
            rules.append(rule)
            triggered_reasons.append("NEW_VENDOR_FIRST_PAYMENT")
            if substate == "STANDARD_REVIEW":
                substate = "HIGH_PRIORITY_REVIEW"
            logger.info(f"[{ctx.invoice_id}] Override: new vendor first payment")
        else:
            rules.append(RuleEvaluation(
                rule_id="NEW_VENDOR_OVERRIDE",
                result="NOT_TRIGGERED",
                priority=4,
                detail="New vendor but amount below threshold" if ctx.is_first_payment else "Not first payment",
            ))
    else:
        rules.append(RuleEvaluation(
            rule_id="NEW_VENDOR_OVERRIDE",
            result="NOT_TRIGGERED",
            priority=4,
            detail="Not a first payment",
        ))

    # --- 3. Sub-threshold Clustering ---
    clustering_signals = [
        s for s in ctx.fraud_signals
        if s.get("signal_type") == "THRESHOLD_SHAVING"
    ]
    if clustering_signals:
        rule = RuleEvaluation(
            rule_id="CLUSTERING_OVERRIDE",
            result="TRIGGERED",
            priority=4,
            detail=f"Threshold shaving signals detected: {len(clustering_signals)}",
            inputs={"clustering_signals": len(clustering_signals)},
        )
        rules.append(rule)
        triggered_reasons.append("THRESHOLD_CLUSTERING")
        if substate == "STANDARD_REVIEW":
            substate = "FRAUD_REVIEW"
        logger.info(f"[{ctx.invoice_id}] Override: threshold clustering")
    else:
        rules.append(RuleEvaluation(
            rule_id="CLUSTERING_OVERRIDE",
            result="NOT_TRIGGERED",
            priority=4,
            detail="No clustering signals",
        ))

    # --- 4. High-severity fraud signals → FRAUD_REVIEW ---
    high_fraud = [
        s for s in ctx.fraud_signals
        if s.get("severity") in ("HIGH", "CRITICAL")
    ]
    if high_fraud:
        rule = RuleEvaluation(
            rule_id="HIGH_FRAUD_OVERRIDE",
            result="TRIGGERED",
            priority=3,
            detail=f"High-severity fraud signals: {len(high_fraud)}",
            inputs={"high_fraud_count": len(high_fraud)},
        )
        rules.append(rule)
        triggered_reasons.append("HIGH_FRAUD_SIGNAL")
        substate = "FRAUD_REVIEW"
        logger.info(f"[{ctx.invoice_id}] Override: high fraud signals")
    else:
        rules.append(RuleEvaluation(
            rule_id="HIGH_FRAUD_OVERRIDE",
            result="NOT_TRIGGERED",
            priority=3,
            detail="No high-severity fraud signals",
        ))

    # --- Result ---
    if triggered_reasons:
        return OverrideResult(
            triggered=True,
            decision="REVIEW_REQUIRED",
            substate=substate,
            reason_codes=triggered_reasons,
            rules=rules,
        )

    return OverrideResult(triggered=False, rules=rules)
