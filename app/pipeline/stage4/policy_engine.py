"""
InvoiceFlow AI — Stage 4: Policy Engine

Steps 4-6 of the 10-step decision pipeline:
  Step 4: Stage 3 state mapping
  Step 5: Policy resolution (effective policy)
  Step 6: Policy evaluation (materiality, risk, precedence)

Decision precedence (PRD Section 11.1, 15):
  P0: System integrity
  P1: Legal/regulatory
  P2: Security controls
  P3: Stage 3 terminal
  P4: Enterprise controls
  P5: Vendor risk
  P6: Materiality
  P7: Delegation of authority
  P8: Routing/SLA
  P9: Automation defaults
"""

import logging
from dataclasses import dataclass

from app.models.decision import RuleEvaluation, PolicyResolution, MaterialityTier
from app.pipeline.stage4.decision_context import DecisionContext

logger = logging.getLogger(__name__)

# Default materiality thresholds (USD)
DEFAULT_AUTO_APPROVE_LIMIT = 5000.0
DEFAULT_MANAGER_LIMIT = 50000.0
DEFAULT_DIRECTOR_LIMIT = 500000.0


@dataclass
class PolicyResult:
    """Result of policy evaluation (steps 4-6)."""
    decision: str | None = None       # Set if policy determines outcome
    substate: str | None = None
    reason_codes: list[str] | None = None
    policy: PolicyResolution | None = None
    rules: list[RuleEvaluation] | None = None
    continue_to_authority: bool = False  # True if VALIDATED and needs authority check


# ═══════════════════════════════════════════════════════════
# Step 4: Stage 3 State Mapping
# ═══════════════════════════════════════════════════════════

def _map_stage3_state(ctx: DecisionContext) -> tuple[str | None, str | None, list[str], RuleEvaluation]:
    """
    Map Stage 3 overall_state to Stage 4 disposition.

    Returns:
        (decision, substate, reason_codes, rule)
    """
    state = ctx.validation_state

    if state == "HOLD":
        # Determine review priority based on reason codes
        has_price = "PRICE_VARIANCE_EXCEEDED" in ctx.reason_codes
        has_budget = "BUDGET_EXCEEDED" in ctx.reason_codes
        has_tax = "TAX_VARIANCE" in ctx.reason_codes

        if has_price or has_budget or has_tax:
            substate = "HIGH_PRIORITY_REVIEW"
        else:
            substate = "STANDARD_REVIEW"

        rule = RuleEvaluation(
            rule_id="STAGE3_STATE",
            result="TRIGGERED",
            priority=5,
            detail=f"Stage 3 HOLD: {', '.join(ctx.reason_codes)}",
            inputs={"stage3_state": state, "reason_codes": ctx.reason_codes},
        )
        return "REVIEW_REQUIRED", substate, list(ctx.reason_codes), rule

    elif state == "REVIEW_REQUIRED":
        rule = RuleEvaluation(
            rule_id="STAGE3_STATE",
            result="TRIGGERED",
            priority=6,
            detail=f"Stage 3 REVIEW_REQUIRED: {', '.join(ctx.reason_codes)}",
            inputs={"stage3_state": state, "reason_codes": ctx.reason_codes},
        )
        return "REVIEW_REQUIRED", "STANDARD_REVIEW", list(ctx.reason_codes), rule

    elif state == "VALIDATION_INCOMPLETE":
        # Check for GRN-specific wait
        has_grn_missing = "GRN_MISSING" in ctx.reason_codes
        substate = "WAITING_FOR_GRN" if has_grn_missing else "WAITING_FOR_REQUIRED_DATA"

        rule = RuleEvaluation(
            rule_id="STAGE3_STATE",
            result="TRIGGERED",
            priority=4,
            detail=f"Stage 3 VALIDATION_INCOMPLETE: {', '.join(ctx.reason_codes)}",
            inputs={"stage3_state": state, "reason_codes": ctx.reason_codes},
        )
        return "WAITING_FOR_VALIDATION", substate, list(ctx.reason_codes), rule

    elif state == "VALIDATED":
        rule = RuleEvaluation(
            rule_id="STAGE3_STATE",
            result="NOT_TRIGGERED",
            priority=9,
            detail="Stage 3 VALIDATED — continue to policy evaluation",
        )
        return None, None, [], rule  # Continue to policy

    else:
        # Unknown state — fail closed
        rule = RuleEvaluation(
            rule_id="STAGE3_STATE",
            result="ERROR",
            priority=0,
            detail=f"Unknown Stage 3 state: {state}",
        )
        return "REVIEW_REQUIRED", "POLICY_EXCEPTION_REVIEW", ["UNKNOWN_VALIDATION_STATE"], rule


# ═══════════════════════════════════════════════════════════
# Step 5: Policy Resolution
# ═══════════════════════════════════════════════════════════

def _resolve_policy(
    ctx: DecisionContext,
    auto_approve_limit: float = DEFAULT_AUTO_APPROVE_LIMIT,
    manager_limit: float = DEFAULT_MANAGER_LIMIT,
    director_limit: float = DEFAULT_DIRECTOR_LIMIT,
) -> PolicyResolution:
    """Resolve the effective policy for this invoice."""

    # Determine materiality tier
    amount = ctx.amount or 0
    if amount <= auto_approve_limit:
        tier: MaterialityTier = "LOW"
        auto_eligible = True
    elif amount <= manager_limit:
        tier = "MEDIUM"
        auto_eligible = False
    elif amount <= director_limit:
        tier = "HIGH"
        auto_eligible = False
    else:
        tier = "CRITICAL"
        auto_eligible = False

    # Determine vendor risk tier
    risk_tier = ctx.vendor_risk_tier
    if ctx.vendor_status in ("inactive", "suspended"):
        risk_tier = "HIGH"
    elif ctx.is_first_payment:
        risk_tier = "ELEVATED"

    # High-risk vendor disables auto-approval
    if risk_tier in ("HIGH", "ELEVATED"):
        auto_eligible = False

    # Matching policy: identity fields required for auto-approval
    from app.pipeline.policy_loader import load_matching_policy

    required_fields = load_matching_policy().get("approval", {}).get(
        "required_for_auto_approval", ["invoice_number", "invoice_date"]
    )
    extraction_snap = ctx.source_snapshots.get("extraction") or {}
    for field_name in required_fields:
        field_data = extraction_snap.get(field_name)
        value = field_data.get("value") if isinstance(field_data, dict) else field_data
        if not value:
            auto_eligible = False
            break

    return PolicyResolution(
        policy_id="AP-DEFAULT",
        policy_version=ctx.policy_version or "AP-2026.08.1",
        materiality_tier=tier,
        auto_approve_eligible=auto_eligible,
        approval_limit=auto_approve_limit,
        risk_tier=risk_tier,
    )


# ═══════════════════════════════════════════════════════════
# Step 6: Policy Evaluation
# ═══════════════════════════════════════════════════════════

def evaluate_policy(
    ctx: DecisionContext,
    auto_approve_limit: float = DEFAULT_AUTO_APPROVE_LIMIT,
    manager_limit: float = DEFAULT_MANAGER_LIMIT,
    director_limit: float = DEFAULT_DIRECTOR_LIMIT,
) -> PolicyResult:
    """
    Evaluate policy: Stage 3 state mapping + policy resolution + evaluation.

    Returns:
        PolicyResult with decision or continue_to_authority flag.
    """
    rules = []

    # --- Step 4: Stage 3 State Mapping ---
    decision, substate, reason_codes, state_rule = _map_stage3_state(ctx)
    rules.append(state_rule)

    if decision is not None:
        # Stage 3 state determines outcome (HOLD/REVIEW/INCOMPLETE)
        policy = _resolve_policy(ctx, auto_approve_limit, manager_limit, director_limit)
        return PolicyResult(
            decision=decision,
            substate=substate,
            reason_codes=reason_codes,
            policy=policy,
            rules=rules,
            continue_to_authority=False,
        )

    # --- Step 5: Policy Resolution ---
    policy = _resolve_policy(ctx, auto_approve_limit, manager_limit, director_limit)

    # --- Step 6: Policy Evaluation ---
    # Check: no applicable policy?
    if not policy.policy_id:
        rule = RuleEvaluation(
            rule_id="POLICY_NO_MATCH",
            result="TRIGGERED",
            priority=7,
            detail="No applicable policy found — fail closed",
        )
        rules.append(rule)
        return PolicyResult(
            decision="WAITING_FOR_VALIDATION",
            substate="POLICY_CONFIGURATION_ERROR",
            reason_codes=["NO_APPLICABLE_POLICY"],
            policy=policy,
            rules=rules,
        )

    # Materiality evaluation
    rule = RuleEvaluation(
        rule_id=f"MATERIALITY_{policy.materiality_tier}",
        result="TRIGGERED" if not policy.auto_approve_eligible else "NOT_TRIGGERED",
        priority=6,
        detail=(
            f"Amount ${ctx.amount or 0:,.2f} → tier {policy.materiality_tier}"
            + (" (auto-approve eligible)" if policy.auto_approve_eligible else " (approval required)")
        ),
        inputs={
            "amount": ctx.amount,
            "tier": policy.materiality_tier,
            "auto_approve_limit": auto_approve_limit,
        },
    )
    rules.append(rule)

    # Risk evaluation
    if policy.risk_tier in ("HIGH", "ELEVATED"):
        rule = RuleEvaluation(
            rule_id="VENDOR_RISK",
            result="TRIGGERED",
            priority=5,
            detail=f"Vendor risk tier: {policy.risk_tier} — auto-approval disabled",
            inputs={"risk_tier": policy.risk_tier, "vendor_id": ctx.vendor_id},
        )
        rules.append(rule)

    # If auto-approve eligible → will be finalized in authority step
    # If not → will need approval
    return PolicyResult(
        decision=None,  # Continue to authority
        policy=policy,
        rules=rules,
        continue_to_authority=True,
    )
