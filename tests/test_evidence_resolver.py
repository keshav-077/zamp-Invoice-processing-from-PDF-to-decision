"""Tests for Stage 5 evidence resolver."""

import json
from unittest.mock import patch

from app.models.decision import (
    DecisionRecord,
    DecisionTrace,
    PolicyResolution,
    AuthorityResolution,
    RoutingDecision,
)
from app.pipeline.stage5.evidence_resolver import (
    UpstreamEvidenceContext,
    resolve_evidence,
)


def _decision_record(**kwargs) -> DecisionRecord:
    return DecisionRecord(
        decision_id="DEC-TEST",
        invoice_id="INV-TEST",
        validation_run_id=kwargs.get("validation_run_id", "VR-TEST"),
        decision=kwargs.get("decision", "APPROVE"),
        decision_substate=kwargs.get("substate", "AUTO_APPROVED"),
        trace=DecisionTrace(
            policy=PolicyResolution(
                policy_id="AP-DEFAULT",
                policy_version="AP-2026.08.1",
                materiality_tier="LOW",
                auto_approve_eligible=True,
            ),
            authority=AuthorityResolution(),
            routing=RoutingDecision(),
        ),
    )


class TestInMemoryContext:
    @patch("app.pipeline.stage5.evidence_resolver.repository")
    def test_resolves_from_context_without_db_run(self, mock_repo):
        mock_repo.get_run.return_value = None
        mock_repo.get_match_result.return_value = None
        mock_repo.get_validation_history.return_value = []

        context = UpstreamEvidenceContext(
            extraction={"vendor_name": {"value": "Acme"}},
            match_package={"match_status": "matched", "invoice_id": "INV-TEST"},
            validation_report={"validation_run_id": "VR-TEST", "overall_state": "VALIDATED"},
        )
        result = resolve_evidence("INV-TEST", _decision_record(), context=context)

        assert len(result.gaps) == 0
        assert len(result.artifacts) == 4
        stages = {a.stage for a in result.artifacts}
        assert stages == {1, 2, 3, 4}
        mock_repo.get_run.assert_not_called()

    @patch("app.pipeline.stage5.evidence_resolver.repository")
    def test_falls_back_to_po_match_results(self, mock_repo):
        mock_repo.get_run.return_value = None
        mock_repo.get_match_result.return_value = {
            "document_id": "INV-TEST",
            "match_status": "matched",
            "match_package_json": json.dumps({"match_status": "matched"}),
        }
        mock_repo.get_validation_history.return_value = [
            {"validation_run_id": "VR-TEST", "overall_state": "VALIDATED"},
        ]

        result = resolve_evidence("INV-TEST", _decision_record())

        stage2 = [a for a in result.artifacts if a.stage == 2]
        assert len(stage2) == 1
        assert stage2[0].resolved is True
        mock_repo.get_match_result.assert_called_once_with("INV-TEST")


class TestMissingEvidence:
    @patch("app.pipeline.stage5.evidence_resolver.repository")
    def test_records_gaps_when_nothing_available(self, mock_repo):
        mock_repo.get_run.return_value = None
        mock_repo.get_match_result.return_value = None
        mock_repo.get_validation_history.return_value = []

        result = resolve_evidence("INV-TEST", _decision_record())

        gap_stages = {g.stage for g in result.gaps}
        assert gap_stages == {1, 2, 3}
        assert len(result.artifacts) == 1
