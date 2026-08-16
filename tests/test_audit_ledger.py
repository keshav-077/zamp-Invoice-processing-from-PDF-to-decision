"""
Tests for Stage 5: Hash-Chained Audit Ledger & Integrity Verifier
"""

import pytest
from unittest.mock import patch, MagicMock
from app.pipeline.stage5.audit_ledger import compute_content_hash, append_explanation_audit
from app.pipeline.stage5.integrity_verifier import verify_audit_chain


class TestContentHash:
    def test_deterministic(self):
        h1 = compute_content_hash("test content")
        h2 = compute_content_hash("test content")
        assert h1 == h2

    def test_different_content(self):
        h1 = compute_content_hash("content A")
        h2 = compute_content_hash("content B")
        assert h1 != h2

    def test_sha256_format(self):
        h = compute_content_hash("test")
        assert len(h) == 64  # SHA-256 hex


class TestAppendAudit:
    @patch("app.pipeline.stage5.audit_ledger.repository")
    def test_chains_hashes(self, mock_repo):
        mock_repo.get_last_audit_hash.return_value = "abc123prev"
        mock_repo.append_audit_event.return_value = 1

        seq = append_explanation_audit(
            explanation_id="EXP-001",
            decision_id="DEC-001",
            invoice_id="INV-001",
            explanation_json='{"test": true}',
        )

        assert seq == 1
        call_args = mock_repo.append_audit_event.call_args
        assert call_args.kwargs["previous_hash"] == "abc123prev"
        assert call_args.kwargs["event_type"] == "explanation.created"

    @patch("app.pipeline.stage5.audit_ledger.repository")
    def test_genesis_first_record(self, mock_repo):
        mock_repo.get_last_audit_hash.return_value = "GENESIS"
        mock_repo.append_audit_event.return_value = 1

        append_explanation_audit(
            explanation_id="EXP-001",
            decision_id="DEC-001",
            invoice_id="INV-001",
            explanation_json="{}",
        )

        call_args = mock_repo.append_audit_event.call_args
        assert call_args.kwargs["previous_hash"] == "GENESIS"


class TestChainVerification:
    @patch("app.pipeline.stage5.integrity_verifier.repository")
    def test_empty_chain(self, mock_repo):
        mock_repo.get_audit_chain.return_value = []
        result = verify_audit_chain()
        assert result.status == "EMPTY"

    @patch("app.pipeline.stage5.integrity_verifier.repository")
    def test_intact_chain(self, mock_repo):
        h1 = compute_content_hash("record1")
        h2 = compute_content_hash("record2")
        mock_repo.get_audit_chain.return_value = [
            {"ledger_sequence": 2, "content_hash": h2, "previous_hash": h1},
            {"ledger_sequence": 1, "content_hash": h1, "previous_hash": "GENESIS"},
        ]
        result = verify_audit_chain()
        assert result.status == "INTACT"
        assert result.records_checked == 2

    @patch("app.pipeline.stage5.integrity_verifier.repository")
    def test_broken_prev_hash(self, mock_repo):
        h1 = compute_content_hash("record1")
        h2 = compute_content_hash("record2")
        mock_repo.get_audit_chain.return_value = [
            {"ledger_sequence": 2, "content_hash": h2, "previous_hash": "TAMPERED"},
            {"ledger_sequence": 1, "content_hash": h1, "previous_hash": "GENESIS"},
        ]
        result = verify_audit_chain()
        assert result.status == "BREACH"
        assert len(result.breaches) >= 1
        assert result.breaches[0]["type"] == "PREV_HASH_MISMATCH"

    @patch("app.pipeline.stage5.integrity_verifier.repository")
    def test_sequence_gap(self, mock_repo):
        h1 = compute_content_hash("record1")
        h3 = compute_content_hash("record3")
        mock_repo.get_audit_chain.return_value = [
            {"ledger_sequence": 3, "content_hash": h3, "previous_hash": h1},
            {"ledger_sequence": 1, "content_hash": h1, "previous_hash": "GENESIS"},
        ]
        result = verify_audit_chain()
        assert result.status == "BREACH"
        breach_types = [b["type"] for b in result.breaches]
        assert "SEQUENCE_GAP" in breach_types

    @patch("app.pipeline.stage5.integrity_verifier.repository")
    def test_single_record(self, mock_repo):
        h1 = compute_content_hash("record1")
        mock_repo.get_audit_chain.return_value = [
            {"ledger_sequence": 1, "content_hash": h1, "previous_hash": "GENESIS"},
        ]
        result = verify_audit_chain()
        assert result.status == "INTACT"
        assert result.records_checked == 1
