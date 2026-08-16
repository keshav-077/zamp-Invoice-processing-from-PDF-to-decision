"""
Tests for generic no-PO matching, amount scoring, and master data import.
"""
import json
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from app.db.database import init_db, close_db, get_connection
from app.db import repository
from app.db.seed_data import seed_database
from app.models.extraction import (
    FieldExtraction,
    InvoiceExtraction,
    LineItem,
)
from app.models.match import LineMapping, POCandidate, ScoreBreakdown
from app.pipeline.stage2.ambiguity_detector import detect_ambiguity
from app.pipeline.stage2.candidate_discovery import CandidateDiscovery
from app.pipeline.stage2.evidence_scorer import EvidenceScorer
from app.pipeline.stage2.orchestrator import Stage2Orchestrator
from app.services.master_data_importer import MasterDataImporter
from app.services.vendor_identity import normalize_vendor_name


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_file))
    monkeypatch.setenv("AUTO_SEED_ON_STARTUP", "false")
    from app.config import settings

    settings.database_path = str(db_file)
    settings.database_url = ""
    close_db()
    import app.db.database as db_mod

    db_mod._connection = None
    init_db()
    yield db_file
    close_db()
    db_mod._connection = None


def _rogers_extraction() -> InvoiceExtraction:
    lines = [
        LineItem(
            line_number=i + 1,
            description=desc,
            quantity=qty,
            unit_price=price,
            amount=amt,
            confidence=0.9,
        )
        for i, (desc, qty, price, amt) in enumerate(
            [
                ("Giant 50'S Christmas Cracker", 1, 2.89, 2.89),
                ("Set 12 Colour Pencils Spaceboy", 7, 0.65, 4.55),
                ("Heart Ivory Trellis Large", 4, 1.65, 6.60),
                ("Baking Mould Heart White Chocolate", 10, 2.55, 25.50),
                ("Grow Your Own Flowers Set of 3", 9, 7.95, 71.55),
                ("Edwardian Parasol Black", 10, 12.46, 124.60),
                ("Plasters In Tin Vintage Paisley", 8, 1.65, 13.20),
            ]
        )
    ]
    return InvoiceExtraction(
        vendor_name=FieldExtraction(value="Rogers, Smith and Hobbs", confidence=0.9, status="extracted"),
        invoice_number=FieldExtraction(value="INV-ROG-001", confidence=0.95, status="extracted"),
        invoice_date=FieldExtraction(value="2026-08-01", confidence=0.95, status="extracted"),
        currency=FieldExtraction(value="USD", confidence=0.99, status="inferred"),
        total_amount=FieldExtraction(value=300.46, confidence=0.95, status="extracted"),
        subtotal=FieldExtraction(value=248.89, confidence=0.95, status="extracted"),
        tax_amount=FieldExtraction(value=48.04, confidence=0.95, status="extracted"),
        po_reference=FieldExtraction(value=None, confidence=0.0, status="not_found"),
        line_items=lines,
    )


def _seed_rogers_po(tmp_db, vendor_id: str = "V018"):
    """Simulate reviewer-imported PO with mismatched vendor_id on PO vs resolver."""
    repository.ensure_company("DEFAULT", "Default")
    repository.upsert_vendors(
        [
            {
                "vendor_id": vendor_id,
                "company_id": "DEFAULT",
                "name": "Rogers, Smith and Hobbs",
                "normalized_name": normalize_vendor_name("Rogers, Smith and Hobbs"),
                "aliases_json": "[]",
                "tax_id": None,
                "supplier_code": "ROGERS",
                "status": "active",
            }
        ]
    )
    repository.upsert_purchase_orders(
        [
            {
                "po_number": "PO-ROGERS-01",
                "company_id": "DEFAULT",
                "vendor_id": "V019",  # deliberate mismatch — name match must still work
                "vendor_name": "Rogers, Smith and Hobbs",
                "total_amount": 10000.0,
                "currency": "USD",
                "status": "open",
                "po_type": "standard",
                "issue_date": "2026-06-01",
                "expiry_date": None,
                "received_amount": 0.0,
                "previously_invoiced": 0.0,
            }
        ]
    )
    lines = [
        ("Giant 50'S Christmas Cracker", 1, 2.89, 2.89),
        ("Set 12 Colour Pencils Spaceboy", 7, 0.65, 4.55),
        ("Heart Ivory Trellis Large", 4, 1.65, 6.60),
        ("Baking Mould Heart White Chocolate", 10, 2.55, 25.50),
        ("Grow Your Own Flowers Set of 3", 9, 7.95, 71.55),
        ("Edwardian Parasol Black", 10, 12.46, 124.60),
        ("Plasters In Tin Vintage Paisley", 8, 1.65, 13.20),
    ]
    repository.upsert_po_lines(
        [
            {
                "company_id": "DEFAULT",
                "po_number": "PO-ROGERS-01",
                "line_number": i + 1,
                "description": d,
                "sku": None,
                "quantity": q,
                "unit_price": p,
                "amount": a,
                "uom": "each",
            }
            for i, (d, q, p, a) in enumerate(lines)
        ]
    )
    repository.upsert_grn_records(
        [
            {
                "grn_id": "GRN-ROGERS-01",
                "company_id": "DEFAULT",
                "po_number": "PO-ROGERS-01",
                "received_date": "2026-07-01",
                "received_amount": 10000.0,
                "status": "confirmed",
            }
        ]
    )


class TestAmountScoringPartialPO:
    def test_partial_invoice_gets_full_amount_score(self):
        scorer = EvidenceScorer()
        breakdown, _ = scorer.score(
            retrieval_method="vendor_search",
            retrieval_confidence=0.75,
            resolved_vendor_id="V018",
            candidate_vendor_id="V018",
            vendor_confidence=0.9,
            line_mappings=[],
            invoice_total=300.46,
            po_total=10000,
            invoice_date=None,
            po_issue_date="2026-06-01",
            po_remaining=10000,
            balance_ok=True,
        )
        assert breakdown.amount_match == 10.0

    def test_wrong_vendor_gets_zero_vendor_score(self):
        scorer = EvidenceScorer()
        breakdown, _ = scorer.score(
            retrieval_method="vendor_search",
            retrieval_confidence=0.75,
            resolved_vendor_id="V018",
            candidate_vendor_id="V006",
            vendor_confidence=0.9,
            line_mappings=[],
            invoice_total=300.46,
            po_total=10000,
            invoice_date=None,
            po_issue_date="2026-06-01",
            po_remaining=10000,
            balance_ok=True,
        )
        assert breakdown.vendor_match == 0.0


class TestCandidateDiscoveryNoBroadcast:
    def test_finds_po_by_vendor_name_not_id(self, tmp_db):
        _seed_rogers_po(tmp_db)
        discovery = CandidateDiscovery()
        candidates = discovery.discover(
            po_value=None,
            vendor_id="V018",
            vendor_name="Rogers, Smith and Hobbs",
            confidence_action="expand",
            invoice_total=300.46,
            suggestion_mode=True,
        )
        po_numbers = [c["po_number"] for c in candidates]
        assert "PO-ROGERS-01" in po_numbers
        methods = {c["po_number"]: c.get("_retrieval_method") for c in candidates}
        assert methods["PO-ROGERS-01"] in ("vendor_name", "vendor_search", "vendor_amount")

    def test_no_broadcast_to_unrelated_vendors(self, tmp_db):
        seed_database()
        _seed_rogers_po(tmp_db)
        discovery = CandidateDiscovery()
        candidates = discovery.discover(
            po_value=None,
            vendor_id="V018",
            vendor_name="Rogers, Smith and Hobbs",
            confidence_action="expand",
            invoice_total=300.46,
            suggestion_mode=True,
        )
        for c in candidates:
            assert c.get("_retrieval_method") != "broadcast"


class TestRogersStage2Integration:
    def test_clean_rogers_auto_matches_without_po_on_invoice(self, tmp_db):
        seed_database()
        _seed_rogers_po(tmp_db)
        extraction = _rogers_extraction()
        package = Stage2Orchestrator().match(
            document_id="test-rogers-clean",
            extraction=extraction,
            suggestion_mode=True,
        )
        assert package.match_status in ("high_confidence_match", "matched", "waiting_for_grn")
        assert package.matched_pos
        assert package.matched_pos[0].po_number == "PO-ROGERS-01"
        assert package.match_provenance == "evidence"


class TestNoPoEvidenceGate:
    def test_strong_evidence_auto_matches(self):
        top = POCandidate(
            po_number="PO-1",
            vendor_id="V1",
            score=ScoreBreakdown(
                po_match=5,
                vendor_match=18,
                line_match=17,
                amount_match=10,
                date_match=2,
            ),
            line_mappings=[
                LineMapping(
                    invoice_line=i,
                    po_number="PO-1",
                    po_line=i,
                    match_type="exact",
                    similarity_score=0.9,
                )
                for i in range(1, 8)
            ],
        )
        second = POCandidate(
            po_number="PO-2",
            vendor_id="V2",
            score=ScoreBreakdown(vendor_match=0, line_match=5, amount_match=1),
            line_mappings=[],
        )
        status, selected = detect_ambiguity([top, second], suggestion_mode=True)
        assert status == "high_confidence_match"
        assert selected[0].po_number == "PO-1"


class TestMasterDataImport:
    def test_preview_and_commit_xlsx(self, tmp_db):
        import io

        vendors = pd.DataFrame(
            [
                {
                    "vendor_id": "V100",
                    "name": "Acme Supplies",
                    "tax_id": "TAX100",
                    "supplier_code": "ACME",
                    "status": "active",
                }
            ]
        )
        pos = pd.DataFrame(
            [
                {
                    "po_number": "PO-ACME-01",
                    "supplier_code": "ACME",
                    "vendor_name": "Acme Supplies",
                    "total_amount": 5000,
                    "currency": "USD",
                    "status": "open",
                    "issue_date": "2026-01-01",
                }
            ]
        )
        lines = pd.DataFrame(
            [
                {
                    "po_number": "PO-ACME-01",
                    "line_number": 1,
                    "description": "Widget",
                    "quantity": 10,
                    "unit_price": 50,
                    "amount": 500,
                }
            ]
        )
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            vendors.to_excel(writer, sheet_name="Vendors", index=False)
            pos.to_excel(writer, sheet_name="PurchaseOrders", index=False)
            lines.to_excel(writer, sheet_name="POLines", index=False)
        content = buf.getvalue()

        importer = MasterDataImporter()
        preview = importer.preview(content, "test.xlsx")
        assert preview["valid"] is True
        assert preview["summary"]["vendors"] == 1

        commit = importer.commit(content, "test.xlsx")
        assert commit["committed"] is True
        po = repository.get_po("PO-ACME-01")
        assert po is not None
        assert po["vendor_id"] == "V100"


class TestInvoiceAllocationIdempotency:
    def test_double_posting_is_idempotent(self, tmp_db):
        _seed_rogers_po(tmp_db, vendor_id="V019")
        first = repository.record_invoice_allocation("doc-1", "PO-ROGERS-01", 300.46)
        second = repository.record_invoice_allocation("doc-1", "PO-ROGERS-01", 300.46)
        assert first is True
        assert second is False
        po = repository.get_po("PO-ROGERS-01")
        assert po["previously_invoiced"] == pytest.approx(300.46)
