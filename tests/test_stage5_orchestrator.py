"""
Tests for Stage 5: Explanation Orchestrator

Integration tests covering PRD acceptance criteria (A1-A10).
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from app.models.decision import (
    DecisionRecord, DecisionTrace, RuleEvaluation,
    PolicyResolution, AuthorityResolution, RoutingDecision,
)
from app.pipeline.stage5.orchestrator import Stage5Orchestrator


def _make_decision(
    decision="APPROVE",
    substate="AUTO_APPROVED",
    reason_codes=None,
    rules=None,
    policy=None,
    authority=None,
    routing=None,
) -> DecisionRecord:
    return DecisionRecord(
        invoice_id="INV-TEST",
        validation_run_id="VR-TEST",
        decision=decision,
        decision_substate=substate,
        reason_codes=reason_codes or [],
        evidence_refs=["stage3:validation:VR-TEST"],
        evidence_summary=["All checks passed"],
        trace=DecisionTrace(
            rules_evaluated=rules or [
                RuleEvaluation(
                    rule_id="HARD_CONTROL_GATE", result="NOT_TRIGGERED",
                    priority=1, detail="No terminal controls",
                ),
            ],
            policy=policy or PolicyResolution(
                policy_id="AP-DEFAULT", policy_version="AP-2026.08.1",
                materiality_tier="LOW", auto_approve_eligible=True,
            ),
            authority=authority or AuthorityResolution(),
            routing=routing or RoutingDecision(),
            stage3_state_used="VALIDATED",
            decision_path=["GATE", "POLICY", "AUTHORITY"],
        ),
    )


# ═══════════════════════════════════════════════════════════
# A1: Duplicate decision event → one canonical explanation
# ═══════════════════════════════════════════════════════════

class TestIdempotency:
    @patch("app.pipeline.stage5.orchestrator.repository")
    @patch("app.pipeline.stage5.evidence_resolver.repository")
    @patch("app.pipeline.stage5.audit_ledger.repository")
    def test_duplicate_returns_existing(self, mock_audit, mock_evidence, mock_orch):
        # First call: no existing
        mock_orch.get_explanation_by_decision.return_value = {
            "explanation_id": "EXP-EXISTING",
            "explanation_status": "COMPLETE",
            "generated_at": "2026-01-01T00:00:00",
        }

        record = _make_decision()
        orch = Stage5Orchestrator()
        result = orch.explain("INV-TEST", record)

        assert result.explanation_id == "EXP-EXISTING"
        # Should NOT have called save_explanation
        mock_orch.save_explanation.assert_not_called()


# ═══════════════════════════════════════════════════════════
# A3: Full pipeline produces COMPLETE explanation
# ═══════════════════════════════════════════════════════════

class TestFullPipeline:
    @patch("app.pipeline.stage5.orchestrator.repository")
    @patch("app.pipeline.stage5.evidence_resolver.repository")
    @patch("app.pipeline.stage5.audit_ledger.repository")
    def test_auto_approved_complete(self, mock_audit, mock_evidence, mock_orch):
        mock_orch.get_explanation_by_decision.return_value = None
        mock_orch.get_last_audit_hash.return_value = "GENESIS"
        mock_orch.save_explanation.return_value = None
        mock_audit.get_last_audit_hash.return_value = "GENESIS"
        mock_audit.append_audit_event.return_value = 1

        mock_evidence.get_run.return_value = {
            "extraction_json": {"field": "value"},
            "stage2_result_json": {"match": "data"},
        }
        mock_evidence.get_validation_history.return_value = [
            {"validation_run_id": "VR-TEST"},
        ]

        record = _make_decision()
        orch = Stage5Orchestrator()
        result = orch.explain("INV-TEST", record)

        assert result.explanation_status == "COMPLETE"
        assert result.explanation_id.startswith("EXP-")
        assert result.decision_outcome == "APPROVE"
        assert result.decision_substate == "AUTO_APPROVED"
        assert len(result.narrative) > 0
        assert result.processing_time_seconds >= 0

    @patch("app.pipeline.stage5.orchestrator.repository")
    @patch("app.pipeline.stage5.evidence_resolver.repository")
    @patch("app.pipeline.stage5.audit_ledger.repository")
    def test_reject_complete(self, mock_audit, mock_evidence, mock_orch):
        mock_orch.get_explanation_by_decision.return_value = None
        mock_orch.get_last_audit_hash.return_value = "GENESIS"
        mock_orch.save_explanation.return_value = None
        mock_audit.get_last_audit_hash.return_value = "GENESIS"
        mock_audit.append_audit_event.return_value = 1

        mock_evidence.get_run.return_value = {
            "extraction_json": {"field": "value"},
            "stage2_result_json": {"match": "data"},
        }
        mock_evidence.get_validation_history.return_value = [
            {"validation_run_id": "VR-TEST"},
        ]

        record = _make_decision(
            decision="REJECT", substate="TERMINAL_REJECT",
            reason_codes=["DUPLICATE_CONFIRMED"],
        )
        orch = Stage5Orchestrator()
        result = orch.explain("INV-TEST", record)

        assert result.explanation_status == "COMPLETE"
        assert result.decision_outcome == "REJECT"
        assert len(result.narrative) > 0


# ═══════════════════════════════════════════════════════════
# A4: AUTO_APPROVE gets same audit rigor
# ═══════════════════════════════════════════════════════════

class TestAuditParity:
    @patch("app.pipeline.stage5.orchestrator.repository")
    @patch("app.pipeline.stage5.evidence_resolver.repository")
    @patch("app.pipeline.stage5.audit_ledger.repository")
    def test_auto_approve_full_trace(self, mock_audit, mock_evidence, mock_orch):
        mock_orch.get_explanation_by_decision.return_value = None
        mock_orch.get_last_audit_hash.return_value = "GENESIS"
        mock_audit.get_last_audit_hash.return_value = "GENESIS"
        mock_audit.append_audit_event.return_value = 1
        mock_evidence.get_run.return_value = {
            "extraction_json": {"f": "v"},
            "stage2_result_json": {"m": "d"},
        }
        mock_evidence.get_validation_history.return_value = [{"validation_run_id": "VR-T"}]

        record = _make_decision()
        orch = Stage5Orchestrator()
        result = orch.explain("INV-TEST", record)

        assert result.explanation_status == "COMPLETE"
        assert len(result.rule_trace_summary) > 0
        assert result.policy_version != ""
        assert result.policy_hash != ""
        assert len(result.upstream_artifacts) > 0
        assert len(result.control_verifications) > 0


# ═══════════════════════════════════════════════════════════
# A5: Control required but missing → PENDING
# ═══════════════════════════════════════════════════════════

class TestControlVerification:
    @patch("app.pipeline.stage5.orchestrator.repository")
    @patch("app.pipeline.stage5.evidence_resolver.repository")
    @patch("app.pipeline.stage5.audit_ledger.repository")
    def test_approval_required_pending(self, mock_audit, mock_evidence, mock_orch):
        mock_orch.get_explanation_by_decision.return_value = None
        mock_orch.get_last_audit_hash.return_value = "GENESIS"
        mock_audit.get_last_audit_hash.return_value = "GENESIS"
        mock_audit.append_audit_event.return_value = 1
        mock_evidence.get_run.return_value = {"extraction_json": {"f": "v"}, "stage2_result_json": {"m": "d"}}
        mock_evidence.get_validation_history.return_value = [{"validation_run_id": "VR-T"}]

        record = _make_decision(
            substate="APPROVAL_REQUIRED",
            authority=AuthorityResolution(
                required=True, approver_group="finance-manager-group",
                required_limit=50000.0,
            ),
        )
        orch = Stage5Orchestrator()
        result = orch.explain("INV-TEST", record)

        pending = [c for c in result.control_verifications if c.status == "PENDING"]
        assert len(pending) >= 1
        assert pending[0].control_type == "APPROVAL"


# ═══════════════════════════════════════════════════════════
# A2: Missing evidence → explicit gap
# ═══════════════════════════════════════════════════════════

class TestEvidenceGaps:
    @patch("app.pipeline.stage5.orchestrator.repository")
    @patch("app.pipeline.stage5.evidence_resolver.repository")
    @patch("app.pipeline.stage5.audit_ledger.repository")
    def test_missing_extraction_gap(self, mock_audit, mock_evidence, mock_orch):
        mock_orch.get_explanation_by_decision.return_value = None
        mock_orch.get_last_audit_hash.return_value = "GENESIS"
        mock_audit.get_last_audit_hash.return_value = "GENESIS"
        mock_audit.append_audit_event.return_value = 1
        mock_evidence.get_run.return_value = {
            "extraction_json": None,
            "stage2_result_json": None,
        }
        mock_evidence.get_validation_history.return_value = []

        record = _make_decision()
        orch = Stage5Orchestrator()
        result = orch.explain("INV-TEST", record)

        gap_stages = [g.stage for g in result.gaps]
        assert 1 in gap_stages  # Missing extraction
        assert 2 in gap_stages  # Missing match
        assert 3 in gap_stages  # Missing validation


# ═══════════════════════════════════════════════════════════
# Invalid input → INCOMPLETE
# ═══════════════════════════════════════════════════════════

class TestInvalidInput:
    def test_no_decision_id(self):
        record = DecisionRecord(
            decision_id="",
            invoice_id="INV-TEST",
            validation_run_id="VR-TEST",
            decision="APPROVE",
            decision_substate="AUTO_APPROVED",
        )
        orch = Stage5Orchestrator()
        result = orch.explain("INV-TEST", record)
        assert result.explanation_status == "INCOMPLETE"


# ═══════════════════════════════════════════════════════════
# A9: Narrative traces to rules
# ═══════════════════════════════════════════════════════════

class TestNarrativeIntegrity:
    @patch("app.pipeline.stage5.orchestrator.repository")
    @patch("app.pipeline.stage5.evidence_resolver.repository")
    @patch("app.pipeline.stage5.audit_ledger.repository")
    def test_narrative_has_source_rules(self, mock_audit, mock_evidence, mock_orch):
        mock_orch.get_explanation_by_decision.return_value = None
        mock_orch.get_last_audit_hash.return_value = "GENESIS"
        mock_audit.get_last_audit_hash.return_value = "GENESIS"
        mock_audit.append_audit_event.return_value = 1
        mock_evidence.get_run.return_value = {"extraction_json": {"f": "v"}, "stage2_result_json": {"m": "d"}}
        mock_evidence.get_validation_history.return_value = [{"validation_run_id": "VR-T"}]

        rules = [
            RuleEvaluation(rule_id="HARD_CONTROL_GATE", result="NOT_TRIGGERED", priority=1, detail="No controls"),
            RuleEvaluation(rule_id="MATERIALITY_LOW", result="TRIGGERED", priority=6, detail="$3000 within limit"),
        ]
        record = _make_decision(rules=rules)
        orch = Stage5Orchestrator()
        result = orch.explain("INV-TEST", record)

        # Every narrative entry must have a source_rule_id
        for entry in result.narrative:
            assert entry.source_rule_id != "", f"Missing source rule for: {entry.text}"


# ═══════════════════════════════════════════════════════════
# Integrity proof
# ═══════════════════════════════════════════════════════════

class TestIntegrity:
    @patch("app.pipeline.stage5.orchestrator.repository")
    @patch("app.pipeline.stage5.evidence_resolver.repository")
    @patch("app.pipeline.stage5.audit_ledger.repository")
    def test_has_integrity_proof(self, mock_audit, mock_evidence, mock_orch):
        mock_orch.get_explanation_by_decision.return_value = None
        mock_orch.get_last_audit_hash.return_value = "GENESIS"
        mock_audit.get_last_audit_hash.return_value = "GENESIS"
        mock_audit.append_audit_event.return_value = 42
        mock_evidence.get_run.return_value = {"extraction_json": {"f": "v"}, "stage2_result_json": {"m": "d"}}
        mock_evidence.get_validation_history.return_value = [{"validation_run_id": "VR-T"}]

        record = _make_decision()
        orch = Stage5Orchestrator()
        result = orch.explain("INV-TEST", record)

        assert result.integrity.algorithm == "SHA-256"
        assert result.integrity.content_hash != ""
        assert result.integrity.previous_hash == "GENESIS"
        assert result.integrity.ledger_sequence == 42
