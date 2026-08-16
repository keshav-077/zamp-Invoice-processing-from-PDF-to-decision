"""
Tests for Stage 4: Decision Data Models
"""

import pytest
from app.models.decision import (
    DecisionRecord, DecisionTrace, RuleEvaluation,
    PolicyResolution, AuthorityResolution, RoutingDecision,
)


class TestRuleEvaluation:
    def test_triggered_rule(self):
        rule = RuleEvaluation(
            rule_id="BANK_CHANGE_OVERRIDE",
            result="TRIGGERED",
            priority=2,
            detail="Bank change detected",
        )
        assert rule.result == "TRIGGERED"
        assert rule.priority == 2

    def test_not_triggered_rule(self):
        rule = RuleEvaluation(rule_id="TEST", result="NOT_TRIGGERED")
        assert rule.result == "NOT_TRIGGERED"
        assert rule.priority == 9  # default


class TestPolicyResolution:
    def test_default_policy(self):
        policy = PolicyResolution()
        assert policy.policy_id == "AP-DEFAULT"
        assert policy.materiality_tier == "MEDIUM"
        assert policy.auto_approve_eligible is False

    def test_low_tier_auto_eligible(self):
        policy = PolicyResolution(materiality_tier="LOW", auto_approve_eligible=True)
        assert policy.auto_approve_eligible is True


class TestDecisionRecord:
    def test_creates_unique_id(self):
        r1 = DecisionRecord(
            invoice_id="INV-001",
            validation_run_id="VR-001",
            decision="APPROVE",
            decision_substate="AUTO_APPROVED",
        )
        r2 = DecisionRecord(
            invoice_id="INV-001",
            validation_run_id="VR-001",
            decision="APPROVE",
            decision_substate="AUTO_APPROVED",
        )
        assert r1.decision_id != r2.decision_id
        assert r1.decision_id.startswith("DEC-")

    def test_serialization(self):
        record = DecisionRecord(
            invoice_id="INV-001",
            validation_run_id="VR-001",
            decision="REJECT",
            decision_substate="TERMINAL_REJECT",
            reason_codes=["DUPLICATE_CONFIRMED"],
        )
        data = record.model_dump()
        assert data["decision"] == "REJECT"
        assert data["reason_codes"] == ["DUPLICATE_CONFIRMED"]
        assert "trace" in data

    def test_json_roundtrip(self):
        record = DecisionRecord(
            invoice_id="INV-001",
            validation_run_id="VR-001",
            decision="APPROVE",
            decision_substate="APPROVAL_REQUIRED",
        )
        json_str = record.model_dump_json()
        restored = DecisionRecord.model_validate_json(json_str)
        assert restored.decision == "APPROVE"
        assert restored.decision_substate == "APPROVAL_REQUIRED"
