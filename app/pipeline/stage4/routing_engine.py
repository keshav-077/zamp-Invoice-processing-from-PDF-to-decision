"""
InvoiceFlow AI — Stage 4: Routing & SLA Engine

Step 9 of the 10-step decision pipeline.

Assigns routing target and SLA based on decision substate.
"""

import logging

from app.models.decision import RoutingDecision

logger = logging.getLogger(__name__)

# Routing configuration by decision substate
ROUTING_CONFIG = {
    # APPROVE substates
    "AUTO_APPROVED": {
        "target": None,
        "priority": "NORMAL",
        "sla_hours": 0,
        "resume_condition": None,
    },
    "APPROVAL_REQUIRED": {
        "target": None,  # Set by authority resolver
        "priority": "NORMAL",
        "sla_hours": 24,
        "resume_condition": None,
    },
    # REVIEW substates
    "STANDARD_REVIEW": {
        "target": "ap-exception-queue",
        "priority": "NORMAL",
        "sla_hours": 48,
        "resume_condition": None,
    },
    "HIGH_PRIORITY_REVIEW": {
        "target": "senior-finance-queue",
        "priority": "HIGH",
        "sla_hours": 8,
        "resume_condition": None,
    },
    "FRAUD_REVIEW": {
        "target": "security-fraud-queue",
        "priority": "URGENT",
        "sla_hours": 4,
        "resume_condition": None,
    },
    "VENDOR_SECURITY_REVIEW": {
        "target": "vendor-security-queue",
        "priority": "HIGH",
        "sla_hours": 4,
        "resume_condition": None,
    },
    "POLICY_EXCEPTION_REVIEW": {
        "target": "policy-admin-queue",
        "priority": "HIGH",
        "sla_hours": 8,
        "resume_condition": None,
    },
    # REJECT substates
    "TERMINAL_REJECT": {
        "target": None,
        "priority": "NORMAL",
        "sla_hours": 0,
        "resume_condition": None,
    },
    # WAITING substates
    "WAITING_FOR_GRN": {
        "target": "receiving-queue",
        "priority": "NORMAL",
        "sla_hours": 72,
        "resume_condition": "GRN_RECEIVED",
    },
    "WAITING_FOR_REQUIRED_DATA": {
        "target": "data-resolution-queue",
        "priority": "NORMAL",
        "sla_hours": 48,
        "resume_condition": "DATA_AVAILABLE",
    },
    "REVALIDATION_REQUIRED": {
        "target": "revalidation-queue",
        "priority": "HIGH",
        "sla_hours": 4,
        "resume_condition": "REVALIDATION_COMPLETE",
    },
    "POLICY_CONFIGURATION_ERROR": {
        "target": "policy-admin-queue",
        "priority": "URGENT",
        "sla_hours": 4,
        "resume_condition": "POLICY_CONFIGURED",
    },
}


def resolve_routing(
    decision_substate: str,
    approver_group: str | None = None,
) -> RoutingDecision:
    """
    Resolve routing target and SLA for a decision.

    Args:
        decision_substate: The decision substate
        approver_group: Override target from authority resolver

    Returns:
        RoutingDecision with target, priority, SLA, and resume condition.
    """
    config = ROUTING_CONFIG.get(decision_substate, {
        "target": "ap-exception-queue",
        "priority": "NORMAL",
        "sla_hours": 48,
        "resume_condition": None,
    })

    target = config["target"]

    # Override target if approver group specified
    if approver_group and decision_substate == "APPROVAL_REQUIRED":
        target = approver_group

    routing = RoutingDecision(
        target=target,
        priority=config["priority"],
        sla_hours=config["sla_hours"],
        resume_condition=config["resume_condition"],
    )

    logger.info(
        f"Routing: {decision_substate} → {target} "
        f"(priority={routing.priority}, SLA={routing.sla_hours}h)"
    )
    return routing
