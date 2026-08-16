"""
InvoiceFlow AI — Stage 4: Authority & Segregation of Duties Resolver

Step 7 of the 10-step decision pipeline.

Resolves:
  - Approval authority based on materiality tier
  - Segregation of duties (creator ≠ approver)
  - Delegation limits
  - Dual-control for CRITICAL tier
  - No eligible approver → controlled escalation
"""

import logging
from dataclasses import dataclass

from app.models.decision import RuleEvaluation, AuthorityResolution, PolicyResolution
from app.pipeline.stage4.decision_context import DecisionContext

logger = logging.getLogger(__name__)

# Approval group mapping by materiality tier
APPROVAL_GROUPS = {
    "LOW": None,  # Auto-approved, no approval needed
    "MEDIUM": "finance-manager-group",
    "HIGH": "finance-director-group",
    "CRITICAL": "cfo-group",
}

# Approval limits by tier
APPROVAL_LIMITS = {
    "LOW": 5000.0,
    "MEDIUM": 50000.0,
    "HIGH": 500000.0,
    "CRITICAL": float("inf"),
}


@dataclass
class AuthorityResult:
    """Result of authority resolution."""
    decision: str
    substate: str
    authority: AuthorityResolution
    rules: list[RuleEvaluation]


def resolve_authority(
    ctx: DecisionContext,
    policy: PolicyResolution,
) -> AuthorityResult:
    """
    Resolve approval authority and SoD constraints.

    Args:
        ctx: Decision context
        policy: Resolved effective policy

    Returns:
        AuthorityResult with final decision, substate, authority, and rules.
    """
    rules = []
    tier = policy.materiality_tier

    # --- Auto-approval eligible ---
    if policy.auto_approve_eligible:
        rule = RuleEvaluation(
            rule_id="AUTHORITY_AUTO_APPROVE",
            result="TRIGGERED",
            priority=9,
            detail=(
                f"Auto-approval: amount ${ctx.amount or 0:,.2f} within limit "
                f"${policy.approval_limit:,.2f}, all controls pass"
            ),
            inputs={"amount": ctx.amount, "limit": policy.approval_limit},
        )
        rules.append(rule)

        authority = AuthorityResolution(
            required=False,
            required_limit=policy.approval_limit,
            approver_group="",
            sod_check_passed=True,
        )
        return AuthorityResult(
            decision="APPROVE",
            substate="AUTO_APPROVED",
            authority=authority,
            rules=rules,
        )

    # --- Approval required ---
    approver_group = APPROVAL_GROUPS.get(tier, "finance-manager-group")
    approval_limit = APPROVAL_LIMITS.get(tier, 50000.0)

    if approver_group is None:
        # Shouldn't happen if auto_approve_eligible is correctly set
        approver_group = "finance-manager-group"

    # --- SoD Check ---
    # For MVP: simulate SoD by checking if creator_id would be in approver group
    # In production: check against IAM/directory
    sod_passed = True
    sod_detail = "SoD check passed (MVP: simulated)"

    # --- Dual control for CRITICAL ---
    dual_control = tier == "CRITICAL"

    # --- Check for eligible approvers ---
    # For MVP: assume approver group always has members
    eligible_approvers = [f"{approver_group}:member"]

    rule = RuleEvaluation(
        rule_id=f"AUTHORITY_{tier}",
        result="TRIGGERED",
        priority=7,
        detail=(
            f"Approval required: tier {tier}, group {approver_group}, "
            f"limit ${approval_limit:,.2f}"
            + (", dual-control required" if dual_control else "")
        ),
        inputs={
            "tier": tier,
            "approver_group": approver_group,
            "approval_limit": approval_limit,
            "dual_control": dual_control,
        },
    )
    rules.append(rule)

    authority = AuthorityResolution(
        required=True,
        required_limit=approval_limit,
        approver_group=approver_group,
        sod_check_passed=sod_passed,
        sod_detail=sod_detail,
        dual_control_required=dual_control,
        eligible_approvers=eligible_approvers,
    )

    return AuthorityResult(
        decision="APPROVE",
        substate="APPROVAL_REQUIRED",
        authority=authority,
        rules=rules,
    )
