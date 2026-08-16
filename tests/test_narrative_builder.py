"""
Tests for Stage 5: Deterministic Narrative Builder
"""

import pytest
from app.models.decision import (
    DecisionRecord, DecisionTrace, RuleEvaluation,
    PolicyResolution, AuthorityResolution, RoutingDecision,
)
from app.pipeline.stage5.narrative_builder import build_narrative


def _make_record(
    decision="APPROVE",
    substate="AUTO_APPROVED",
    reason_codes=None,
    rules=None,
    policy=None,
    authority=None,
    routing=None,
):
    return DecisionRecord(
        invoice_id="INV-001",
        validation_run_id="VR-001",
        decision=decision,
        decision_substate=substate,
        reason_codes=reason_codes or [],
        trace=DecisionTrace(
            rules_evaluated=rules or [],
            policy=policy or PolicyResolution(),
            authority=authority or AuthorityResolution(),
            routing=routing or RoutingDecision(),
            stage3_state_used="VALIDATED",
            decision_path=["GATE", "POLICY", "AUTHORITY"],
        ),
    )


class TestNarrativeSummary:
    def test_auto_approved(self):
        record = _make_record(substate="AUTO_APPROVED")
        narrative = build_narrative(record)
        assert len(narrative) >= 2
        assert "auto-approved" in narrative[1].text.lower()
        assert narrative[1].source_rule_id == "DECISION_SUMMARY"

    def test_terminal_reject(self):
        record = _make_record(decision="REJECT", substate="TERMINAL_REJECT")
        narrative = build_narrative(record)
        assert "rejected" in narrative[1].text.lower()

    def test_review_required(self):
        record = _make_record(decision="REVIEW_REQUIRED", substate="HIGH_PRIORITY_REVIEW")
        narrative = build_narrative(record)
        assert "high-priority" in narrative[1].text.lower()

    def test_waiting_grn(self):
        record = _make_record(decision="WAITING_FOR_VALIDATION", substate="WAITING_FOR_GRN")
        narrative = build_narrative(record)
        assert "goods receipt" in narrative[1].text.lower()


class TestRuleNarrative:
    def test_rule_entries(self):
        rules = [
            RuleEvaluation(
                rule_id="HARD_CONTROL_GATE", result="NOT_TRIGGERED",
                priority=1, detail="No terminal controls"
            ),
            RuleEvaluation(
                rule_id="MATERIALITY_LOW", result="TRIGGERED",
                priority=6, detail="Amount $3000 <= $5000 auto-approve limit"
            ),
        ]
        record = _make_record(rules=rules)
        narrative = build_narrative(record)
        rule_entries = [e for e in narrative if e.category == "rule_evaluation"]
        assert len(rule_entries) == 2
        assert rule_entries[0].source_rule_id == "HARD_CONTROL_GATE"

    def test_triggered_vs_not(self):
        rules = [
            RuleEvaluation(rule_id="TEST_RULE", result="TRIGGERED", priority=1, detail="Test"),
            RuleEvaluation(rule_id="PASS_RULE", result="NOT_TRIGGERED", priority=2, detail="OK"),
        ]
        record = _make_record(rules=rules)
        narrative = build_narrative(record)
        rule_entries = [e for e in narrative if e.category == "rule_evaluation"]
        assert "⚡" in rule_entries[0].icon
        assert "✅" in rule_entries[1].icon


class TestPolicyNarrative:
    def test_includes_policy(self):
        policy = PolicyResolution(
            policy_id="AP-DEFAULT", policy_version="AP-2026.08.1",
            materiality_tier="LOW", auto_approve_eligible=True,
        )
        record = _make_record(policy=policy)
        narrative = build_narrative(record)
        policy_entries = [e for e in narrative if e.category == "policy"]
        assert len(policy_entries) == 1
        assert "AP-DEFAULT" in policy_entries[0].text


class TestAuthorityNarrative:
    def test_includes_authority_when_required(self):
        authority = AuthorityResolution(
            required=True, approver_group="finance-director-group",
            required_limit=50000.0,
        )
        record = _make_record(
            decision="APPROVE", substate="APPROVAL_REQUIRED",
            authority=authority,
        )
        narrative = build_narrative(record)
        auth_entries = [e for e in narrative if e.category == "authority"]
        assert len(auth_entries) == 1
        assert "finance-director-group" in auth_entries[0].text


class TestRoutingNarrative:
    def test_includes_routing(self):
        routing = RoutingDecision(target="ap-exception-queue", priority="MEDIUM", sla_hours=48)
        record = _make_record(
            decision="REVIEW_REQUIRED", substate="STANDARD_REVIEW",
            routing=routing,
        )
        narrative = build_narrative(record)
        route_entries = [e for e in narrative if e.category == "routing"]
        assert len(route_entries) == 1
        assert "ap-exception-queue" in route_entries[0].text


class TestReasonCodes:
    def test_includes_reason_codes(self):
        record = _make_record(
            reason_codes=["PRICE_VARIANCE_EXCEEDED", "DUPLICATE_CONFIRMED"],
        )
        narrative = build_narrative(record)
        code_entries = [e for e in narrative if e.category == "reason_codes"]
        assert len(code_entries) == 1
        assert "PRICE_VARIANCE_EXCEEDED" in code_entries[0].text
