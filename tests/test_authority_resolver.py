"""
Tests for Stage 4: Authority & Segregation of Duties Resolver
"""

import pytest
from app.models.decision import PolicyResolution
from app.pipeline.stage4.decision_context import DecisionContext
from app.pipeline.stage4.authority_resolver import resolve_authority


def _make_ctx(**overrides) -> DecisionContext:
    defaults = dict(
        invoice_id="DOC-TEST",
        validation_run_id="VR-TEST",
        amount=5000.0,
    )
    defaults.update(overrides)
    return DecisionContext(**defaults)


def _make_policy(**overrides) -> PolicyResolution:
    defaults = dict(
        policy_id="AP-DEFAULT",
        policy_version="AP-2026.08.1",
        materiality_tier="MEDIUM",
        auto_approve_eligible=False,
        approval_limit=5000.0,
        risk_tier="STANDARD",
    )
    defaults.update(overrides)
    return PolicyResolution(**defaults)


class TestAutoApproval:
    def test_auto_approve_eligible(self):
        ctx = _make_ctx(amount=3000.0)
        policy = _make_policy(materiality_tier="LOW", auto_approve_eligible=True)
        result = resolve_authority(ctx, policy)
        assert result.decision == "APPROVE"
        assert result.substate == "AUTO_APPROVED"
        assert not result.authority.required

    def test_auto_approve_has_evidence(self):
        ctx = _make_ctx(amount=2000.0)
        policy = _make_policy(materiality_tier="LOW", auto_approve_eligible=True)
        result = resolve_authority(ctx, policy)
        assert len(result.rules) > 0


class TestApprovalRequired:
    def test_medium_tier_needs_manager(self):
        ctx = _make_ctx(amount=25000.0)
        policy = _make_policy(materiality_tier="MEDIUM")
        result = resolve_authority(ctx, policy)
        assert result.decision == "APPROVE"
        assert result.substate == "APPROVAL_REQUIRED"
        assert result.authority.required
        assert result.authority.approver_group == "finance-manager-group"

    def test_high_tier_needs_director(self):
        ctx = _make_ctx(amount=200000.0)
        policy = _make_policy(materiality_tier="HIGH")
        result = resolve_authority(ctx, policy)
        assert result.authority.approver_group == "finance-director-group"

    def test_critical_tier_needs_cfo(self):
        ctx = _make_ctx(amount=1000000.0)
        policy = _make_policy(materiality_tier="CRITICAL")
        result = resolve_authority(ctx, policy)
        assert result.authority.approver_group == "cfo-group"
        assert result.authority.dual_control_required is True


class TestSoD:
    def test_sod_check_passes(self):
        ctx = _make_ctx()
        policy = _make_policy(materiality_tier="MEDIUM")
        result = resolve_authority(ctx, policy)
        assert result.authority.sod_check_passed is True


class TestEligibleApprovers:
    def test_has_eligible_approvers(self):
        ctx = _make_ctx()
        policy = _make_policy(materiality_tier="MEDIUM")
        result = resolve_authority(ctx, policy)
        assert len(result.authority.eligible_approvers) > 0
