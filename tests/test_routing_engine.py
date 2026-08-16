"""
Tests for Stage 4: Routing & SLA Engine
"""

import pytest
from app.pipeline.stage4.routing_engine import resolve_routing


class TestAutoApproved:
    def test_no_routing(self):
        routing = resolve_routing("AUTO_APPROVED")
        assert routing.target is None
        assert routing.sla_hours == 0


class TestApprovalRequired:
    def test_uses_approver_group(self):
        routing = resolve_routing("APPROVAL_REQUIRED", approver_group="finance-director-group")
        assert routing.target == "finance-director-group"
        assert routing.sla_hours == 24

    def test_default_target_without_group(self):
        routing = resolve_routing("APPROVAL_REQUIRED")
        assert routing.target is None  # No default when no group specified


class TestReviewSubstates:
    def test_standard_review(self):
        routing = resolve_routing("STANDARD_REVIEW")
        assert routing.target == "ap-exception-queue"
        assert routing.sla_hours == 48

    def test_high_priority_review(self):
        routing = resolve_routing("HIGH_PRIORITY_REVIEW")
        assert routing.target == "senior-finance-queue"
        assert routing.priority == "HIGH"
        assert routing.sla_hours == 8

    def test_fraud_review(self):
        routing = resolve_routing("FRAUD_REVIEW")
        assert routing.target == "security-fraud-queue"
        assert routing.priority == "URGENT"
        assert routing.sla_hours == 4

    def test_vendor_security_review(self):
        routing = resolve_routing("VENDOR_SECURITY_REVIEW")
        assert routing.target == "vendor-security-queue"


class TestWaitingStates:
    def test_waiting_for_grn(self):
        routing = resolve_routing("WAITING_FOR_GRN")
        assert routing.target == "receiving-queue"
        assert routing.resume_condition == "GRN_RECEIVED"

    def test_revalidation_required(self):
        routing = resolve_routing("REVALIDATION_REQUIRED")
        assert routing.target == "revalidation-queue"
        assert routing.resume_condition == "REVALIDATION_COMPLETE"

    def test_policy_config_error(self):
        routing = resolve_routing("POLICY_CONFIGURATION_ERROR")
        assert routing.target == "policy-admin-queue"
        assert routing.priority == "URGENT"


class TestTerminalReject:
    def test_no_routing(self):
        routing = resolve_routing("TERMINAL_REJECT")
        assert routing.target is None
        assert routing.sla_hours == 0
