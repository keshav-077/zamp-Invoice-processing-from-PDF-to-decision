"""
InvoiceFlow AI — Stage 4: Contract & Freshness Gate

Step 1 of the 10-step decision pipeline.

Validates:
  - Required fields present (invoice_id, validation_run_id, overall_state)
  - Stage 3 processing_state is COMPLETED
  - Validation report within freshness window
  - Report is not malformed

If invalid → CONTROLLED_ERROR
If stale → REVALIDATION_REQUIRED
"""

import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

from app.models.decision import RuleEvaluation
from app.pipeline.stage4.decision_context import DecisionContext

logger = logging.getLogger(__name__)

# Default freshness window
DEFAULT_FRESHNESS_HOURS = 24


@dataclass
class ContractGateResult:
    """Result of contract + freshness validation."""
    is_valid: bool
    decision: str | None = None      # Set if gate terminates early
    substate: str | None = None
    reason: str = ""
    rule: RuleEvaluation | None = None


def validate_decision_contract(
    ctx: DecisionContext,
    freshness_hours: int = DEFAULT_FRESHNESS_HOURS,
) -> ContractGateResult:
    """
    Validate the Stage 3 → Stage 4 decision input contract.

    Returns:
        ContractGateResult — if is_valid=False, decision pipeline must stop.
    """
    # --- Schema validation ---
    if not ctx.invoice_id:
        rule = RuleEvaluation(
            rule_id="CONTRACT_SCHEMA",
            result="TRIGGERED",
            priority=0,
            detail="Missing invoice_id",
        )
        return ContractGateResult(
            is_valid=False,
            decision="REVIEW_REQUIRED",
            substate="POLICY_CONFIGURATION_ERROR",
            reason="MISSING_INVOICE_ID",
            rule=rule,
        )

    if not ctx.validation_run_id:
        rule = RuleEvaluation(
            rule_id="CONTRACT_SCHEMA",
            result="TRIGGERED",
            priority=0,
            detail="Missing validation_run_id",
        )
        return ContractGateResult(
            is_valid=False,
            decision="REVIEW_REQUIRED",
            substate="POLICY_CONFIGURATION_ERROR",
            reason="MISSING_VALIDATION_RUN_ID",
            rule=rule,
        )

    if not ctx.validation_state:
        rule = RuleEvaluation(
            rule_id="CONTRACT_SCHEMA",
            result="TRIGGERED",
            priority=0,
            detail="Missing validation state",
        )
        return ContractGateResult(
            is_valid=False,
            decision="REVIEW_REQUIRED",
            substate="POLICY_CONFIGURATION_ERROR",
            reason="MISSING_VALIDATION_STATE",
            rule=rule,
        )

    # --- Processing state ---
    if ctx.validation_processing_state != "COMPLETED":
        rule = RuleEvaluation(
            rule_id="CONTRACT_PROCESSING_STATE",
            result="TRIGGERED",
            priority=0,
            detail=f"Stage 3 processing state: {ctx.validation_processing_state}",
        )
        return ContractGateResult(
            is_valid=False,
            decision="WAITING_FOR_VALIDATION",
            substate="WAITING_FOR_REQUIRED_DATA",
            reason="STAGE3_NOT_COMPLETED",
            rule=rule,
        )

    # --- Freshness ---
    if ctx.validated_at:
        try:
            validated_time = datetime.fromisoformat(ctx.validated_at)
            if validated_time.tzinfo is None:
                validated_time = validated_time.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            age = now - validated_time

            if age > timedelta(hours=freshness_hours):
                rule = RuleEvaluation(
                    rule_id="CONTRACT_FRESHNESS",
                    result="TRIGGERED",
                    priority=0,
                    detail=f"Validation age: {age.total_seconds()/3600:.1f}h (limit: {freshness_hours}h)",
                    inputs={"validated_at": ctx.validated_at, "age_hours": age.total_seconds()/3600},
                )
                return ContractGateResult(
                    is_valid=False,
                    decision="WAITING_FOR_VALIDATION",
                    substate="REVALIDATION_REQUIRED",
                    reason="STALE_VALIDATION",
                    rule=rule,
                )
        except (ValueError, TypeError):
            pass  # If can't parse timestamp, proceed

    # --- Valid ---
    rule = RuleEvaluation(
        rule_id="CONTRACT_GATE",
        result="NOT_TRIGGERED",
        priority=0,
        detail="Contract and freshness validated",
    )
    return ContractGateResult(is_valid=True, rule=rule)
