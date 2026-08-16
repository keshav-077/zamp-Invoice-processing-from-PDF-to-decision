"""
Tests for Stage 5: Explanation Completeness Gate
"""

import pytest
from app.models.explanation import (
    ExplanationSnapshot, NarrativeEntry, UpstreamArtifact,
    EvidenceGap,
)
from app.pipeline.stage5.completeness_gate import validate_completeness


def _make_snapshot(**overrides) -> ExplanationSnapshot:
    """Build a complete snapshot with overridable fields."""
    defaults = dict(
        decision_id="DEC-001",
        invoice_id="INV-001",
        tenant_id="TENANT-DEFAULT",
        policy_version="AP-2026.08.1",
        policy_hash="sha256:abc123",
        decision_outcome="APPROVE",
        decision_substate="AUTO_APPROVED",
        narrative=[NarrativeEntry(step=1, category="test", text="Test")],
        rule_trace_summary=[{"rule_id": "R1", "result": "TRIGGERED"}],
        upstream_artifacts=[
            UpstreamArtifact(stage=4, artifact_id="DEC-001", resolved=True),
        ],
    )
    defaults.update(overrides)
    return ExplanationSnapshot(**defaults)


class TestCompleteSnapshot:
    def test_all_checks_pass(self):
        snapshot = _make_snapshot()
        result = validate_completeness(snapshot)
        assert result.is_complete
        assert len(result.checks_failed) == 0
        assert len(result.checks_passed) >= 9

    def test_complete_has_no_gaps(self):
        snapshot = _make_snapshot()
        result = validate_completeness(snapshot)
        assert len(result.gaps) == 0


class TestMissingFields:
    def test_missing_decision_id(self):
        snapshot = _make_snapshot(decision_id="")
        result = validate_completeness(snapshot)
        assert not result.is_complete
        assert "decision_id" in result.checks_failed

    def test_missing_invoice_id(self):
        snapshot = _make_snapshot(invoice_id="")
        result = validate_completeness(snapshot)
        assert not result.is_complete
        assert "invoice_id" in result.checks_failed

    def test_missing_policy(self):
        snapshot = _make_snapshot(policy_version="")
        result = validate_completeness(snapshot)
        assert not result.is_complete
        assert "policy_version" in result.checks_failed

    def test_missing_outcome(self):
        snapshot = _make_snapshot(decision_outcome="")
        result = validate_completeness(snapshot)
        assert not result.is_complete
        assert "decision_outcome" in result.checks_failed

    def test_empty_rule_trace(self):
        snapshot = _make_snapshot(rule_trace_summary=[])
        result = validate_completeness(snapshot)
        assert not result.is_complete
        assert "rule_trace" in result.checks_failed

    def test_empty_narrative(self):
        snapshot = _make_snapshot(narrative=[])
        result = validate_completeness(snapshot)
        assert not result.is_complete
        assert "narrative" in result.checks_failed

    def test_no_stage4_artifact(self):
        snapshot = _make_snapshot(upstream_artifacts=[
            UpstreamArtifact(stage=1, artifact_id="A1", resolved=True),
        ])
        result = validate_completeness(snapshot)
        assert not result.is_complete
        assert "stage4_artifact" in result.checks_failed


class TestGapsAreExplicit:
    def test_gap_has_stage(self):
        snapshot = _make_snapshot(decision_id="")
        result = validate_completeness(snapshot)
        assert len(result.gaps) >= 1
        assert result.gaps[0].stage == 4

    def test_multiple_gaps(self):
        snapshot = _make_snapshot(
            decision_id="", policy_version="", decision_outcome="",
        )
        result = validate_completeness(snapshot)
        assert len(result.gaps) >= 3
        assert not result.is_complete
