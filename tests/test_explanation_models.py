"""
Tests for Stage 5: Explanation Data Models
"""

import pytest
from app.models.explanation import (
    ExplanationSnapshot, NarrativeEntry, ControlVerification,
    EvidenceGap, HumanAction, IntegrityProof, UpstreamArtifact,
    SamplingAudit,
)


class TestExplanationSnapshot:
    def test_creates_unique_id(self):
        s1 = ExplanationSnapshot(decision_id="D1", invoice_id="I1")
        s2 = ExplanationSnapshot(decision_id="D1", invoice_id="I1")
        assert s1.explanation_id != s2.explanation_id
        assert s1.explanation_id.startswith("EXP-")

    def test_default_schema_version(self):
        s = ExplanationSnapshot(decision_id="D1", invoice_id="I1")
        assert s.explanation_schema_version == "3.0"

    def test_default_tenant(self):
        s = ExplanationSnapshot(decision_id="D1", invoice_id="I1")
        assert s.tenant_id == "TENANT-DEFAULT"

    def test_serialization(self):
        s = ExplanationSnapshot(
            decision_id="DEC-001", invoice_id="INV-001",
            explanation_status="COMPLETE",
            narrative=[NarrativeEntry(step=1, category="test", text="Hello")],
        )
        data = s.model_dump()
        assert data["explanation_status"] == "COMPLETE"
        assert len(data["narrative"]) == 1

    def test_json_roundtrip(self):
        s = ExplanationSnapshot(
            decision_id="DEC-001", invoice_id="INV-001",
            explanation_status="INCOMPLETE",
            gaps=[EvidenceGap(stage=1, artifact_type="extraction", reason="Missing")],
        )
        json_str = s.model_dump_json()
        restored = ExplanationSnapshot.model_validate_json(json_str)
        assert restored.explanation_status == "INCOMPLETE"
        assert len(restored.gaps) == 1


class TestNarrativeEntry:
    def test_has_source_rule(self):
        entry = NarrativeEntry(
            step=1, category="decision", text="Auto-approved",
            source_rule_id="DECISION_SUMMARY",
        )
        assert entry.source_rule_id == "DECISION_SUMMARY"


class TestControlVerification:
    def test_verified(self):
        cv = ControlVerification(
            control_id="CV-1", control_type="APPROVAL", status="VERIFIED",
        )
        assert cv.status == "VERIFIED"

    def test_pending_with_gap(self):
        cv = ControlVerification(
            control_id="CV-1", control_type="APPROVAL", status="PENDING",
            gap_reason="Awaiting approval",
        )
        assert cv.gap_reason != ""


class TestIntegrityProof:
    def test_genesis(self):
        ip = IntegrityProof()
        assert ip.previous_hash == "GENESIS"
        assert ip.algorithm == "SHA-256"
