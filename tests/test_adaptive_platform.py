"""Adversarial tests for adaptive import, tenancy, extraction, matching, and policy."""

from __future__ import annotations

import io
import json
import uuid

import pandas as pd
import pytest

from app.context.tenant import get_company_id, set_company_id
from app.db.database import init_db, close_db
from app.db import repository
from app.models.extraction import (
    FieldExtraction,
    InvoiceExtraction,
    LineItem,
    TypedReference,
)
from app.models.match import POCandidate, LineMapping, ScoreBreakdown
from app.pipeline.stage2.ambiguity_detector import detect_ambiguity
from app.pipeline.stage2.multi_po_resolver import MultiPOResolver
from app.pipeline.stage4.decision_context import DecisionContext
from app.pipeline.stage4.policy_engine import _resolve_policy
from app.pipeline.router import Router
from app.services.adaptive_importer import AdaptiveImporter
from app.services.import_mapper import propose_column_mappings, apply_mappings
from app.services.import_profiler import profile_workbook, file_checksum
from app.services.locale_normalizer import normalize_extraction_locale, parse_amount


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


def _xlsx_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)
    return buf.getvalue()


def test_profile_arbitrary_sheet_names():
    content = _xlsx_bytes(
        {
            "Supplier_List": pd.DataFrame(
                {"supplier_id": ["S1"], "supplier_name": ["Acme Corp"], "gstin": ["GST1"]}
            ),
            "Open_Orders": pd.DataFrame(
                {
                    "ponumber": ["PO-1"],
                    "supplier_name": ["Acme Corp"],
                    "amount": [1000],
                    "po_date": ["2026-01-01"],
                }
            ),
        }
    )
    profile = profile_workbook(content, "orders.xlsx")
    entities = {s["entity"] for s in profile["sheets"]}
    assert "vendor" in entities or "po" in entities
    assert profile["checksum"] == file_checksum(content)


def test_unknown_columns_preserved_in_metadata(tmp_db):
    rows = pd.DataFrame(
        {
            "vendor_id": ["V001"],
            "name": ["Test Vendor"],
            "custom_region": ["EMEA"],
            "legacy_cost_center": ["CC-99"],
        }
    )
    content = _xlsx_bytes({"vendors": rows})
    result = AdaptiveImporter().preview(content, "vendors.xlsx")
    assert result["preview"]["unknown_columns"]
    assert result["summary"]["metadata_fields"] >= 2


def test_company_isolation_identical_po_numbers(tmp_db):
    importer = AdaptiveImporter()
    vendor_sheet = pd.DataFrame({"vendor_id": ["V1"], "name": ["Shared Vendor"]})
    po_sheet = pd.DataFrame(
        {
            "po_number": ["PO-SAME"],
            "vendor_id": ["V1"],
            "vendor_name": ["Shared Vendor"],
            "total_amount": [500],
            "issue_date": ["2026-01-01"],
        }
    )
    content = _xlsx_bytes({"vendors": vendor_sheet, "purchase_orders": po_sheet})

    r1 = importer.commit(content, "a.xlsx", company_id="COMP-A")
    assert r1["valid"], r1.get("errors")
    r2 = importer.commit(content, "b.xlsx", company_id="COMP-B")
    assert r2["valid"]

    po_a = repository.get_po("PO-SAME", company_id="COMP-A")
    po_b = repository.get_po("PO-SAME", company_id="COMP-B")
    assert po_a and po_b
    assert po_a["company_id"] == "COMP-A"
    assert po_b["company_id"] == "COMP-B"


def test_mapping_profile_reuse(tmp_db):
    rows = pd.DataFrame(
        {
            "supplier_number": ["V1"],
            "supplier_name": ["Reuse Co"],
        }
    )
    content = _xlsx_bytes({"suppliers": rows})
    imp = AdaptiveImporter()
    first = imp.commit(content, "v1.xlsx")
    assert first["valid"], first.get("errors")

    second = imp.preview(content, "v2.xlsx")
    sheets = second["preview"]["profile"]["sheets"]
    profile_mappings = [m for s in sheets for m in s.get("column_mappings", [])]
    assert any(m.get("status") == "profile" for m in profile_mappings)


def test_single_candidate_no_po_requires_evidence_gate():
    weak = POCandidate(
        po_number="PO-1",
        vendor_id="V1",
        score=ScoreBreakdown(vendor_match=18, line_match=7, amount_match=1, total=86),
        line_mappings=[
            LineMapping(
                invoice_line=1,
                po_number="PO-1",
                po_line=1,
                match_type="exact",
                similarity_score=0.9,
            )
        ],
    )
    status, selected = detect_ambiguity([weak], suggestion_mode=True, po_presence="non_po")
    assert status in ("waiting_for_po", "suggested_po_match", "unmatched")
    assert not selected or status == "waiting_for_po"


def test_multi_po_resolver_splits_lines():
    resolver = MultiPOResolver()
    mappings = {
        "PO-A": [
            LineMapping(
                invoice_line=1,
                po_number="PO-A",
                po_line=1,
                match_type="exact",
                similarity_score=0.95,
            ),
        ],
        "PO-B": [
            LineMapping(
                invoice_line=2,
                po_number="PO-B",
                po_line=1,
                match_type="exact",
                similarity_score=0.92,
            ),
        ],
    }
    final, unmatched = resolver.resolve(mappings)
    assert len(final) == 2
    assert "PO-A" in final and "PO-B" in final
    assert unmatched == []


def test_auto_approval_blocked_without_invoice_number():
    ctx = DecisionContext(
        amount=100.0,
        source_snapshots={
            "extraction": {
                "invoice_number": {"value": None},
                "invoice_date": {"value": "2026-01-01"},
            }
        },
    )
    policy = _resolve_policy(ctx, auto_approve_limit=5000)
    assert policy.auto_approve_eligible is False


def test_locale_amount_parsing():
    assert parse_amount("(1,234.56)") == -1234.56
    assert parse_amount("1.234,56", {"decimal_sep": ","}) == 1.23456


def test_extraction_locale_normalization():
    ext = InvoiceExtraction(
        currency=FieldExtraction(value="$", confidence=0.9, status="inferred"),
        subtotal=FieldExtraction(value="1,000.00", confidence=0.9, status="extracted"),
        total_amount=FieldExtraction(value=1000.0, confidence=0.9, status="extracted"),
        line_items=[LineItem(description="x", quantity=2, unit_price=50, amount=100)],
    )
    normalized = normalize_extraction_locale(ext)
    assert normalized.currency.value == "USD"


def test_router_matching_signals_vs_approval_fields():
    router = Router()
    ext = InvoiceExtraction(
        vendor_name=FieldExtraction(value="Acme", confidence=0.9, status="extracted"),
        total_amount=FieldExtraction(value=100, confidence=0.9, status="extracted"),
        line_items=[LineItem(description="item", amount=100)],
        invoice_number=FieldExtraction(value=None, status="not_found"),
        invoice_date=FieldExtraction(value=None, status="not_found"),
        currency=FieldExtraction(value=None, status="not_found"),
    )
    assert router.can_run_matching(ext) is True


def test_tenant_context():
    set_company_id("TENANT-X")
    assert get_company_id() == "TENANT-X"
    set_company_id(None)
    assert get_company_id() == "DEFAULT"


def test_atomic_staging_batch(tmp_db):
    batch_id = uuid.uuid4().hex[:12]
    repository.create_staging_batch(
        batch_id=batch_id,
        company_id="DEFAULT",
        filename="t.csv",
        file_checksum="abc",
        source_fingerprint="fp1",
        mapping_json={},
        summary_json={},
    )
    repository.insert_staging_rows(
        batch_id,
        [
            {
                "entity": "vendor",
                "sheet_name": "v",
                "row_index": 0,
                "raw_json": {"name": "X"},
                "canonical_json": {"name": "X"},
                "metadata_json": {"extra": "y"},
            }
        ],
    )
    rows = repository.get_staging_rows(batch_id)
    assert rows[0]["metadata_json"]["extra"] == "y"


def test_column_mapping_confidence():
    mappings = propose_column_mappings("vendor", ["supplier_name", "mystery_col"])
    by_col = {m["source_column"]: m for m in mappings}
    assert by_col["supplier_name"]["canonical_field"] == "name"
    assert by_col["mystery_col"]["status"] == "metadata"


def test_apply_mappings_splits_canonical_and_metadata():
    mappings = propose_column_mappings("vendor", ["name", "region"])
    canonical, metadata = apply_mappings({"name": "Acme", "region": "EU"}, mappings)
    assert canonical.get("name") == "Acme"
    assert metadata.get("region") == "EU"


def test_confirm_clears_review_needed(tmp_db):
    """User-confirmed mappings must not block import with review_needed."""
    rows = pd.DataFrame(
        {
            "vendor_name_on_po": ["New Vendor LLC"],
            "po_number": ["PO-CONF-1"],
            "po_amount": [2500],
            "issue_date": ["2026-01-01"],
        }
    )
    buf = io.BytesIO()
    rows.to_csv(buf, index=False)
    content = buf.getvalue()

    imp = AdaptiveImporter()
    preview = imp.preview(content, "mixed.csv")
    sheets = preview["preview"]["profile"]["sheets"]
    result = imp.commit(content, "mixed.csv", confirmed_mappings=sheets)
    assert not result["review_needed"], result
    assert result["valid"] or result.get("partial_success"), result.get("errors")
    assert result["summary"]["purchase_orders"] >= 1


def test_reimport_same_file_reuses_staging_batch(tmp_db):
    """Second import of the same checksum must not hit UNIQUE constraint."""
    rows = pd.DataFrame(
        {
            "vendor_name_on_invoice": ["Acme Corp"],
            "invoice_number": ["INV-RE-1"],
            "invoice_total": [1000],
        }
    )
    buf = io.BytesIO()
    rows.to_csv(buf, index=False)
    content = buf.getvalue()

    imp = AdaptiveImporter()
    first = imp.commit(content, "transactions.csv")
    assert first.get("valid") or first.get("partial_success"), first.get("errors")

    second = imp.commit(content, "transactions.csv")
    assert second.get("valid") or second.get("partial_success"), second.get("errors")
    assert second["batch_id"] == first["batch_id"]


def test_invalid_po_number_none_skipped_not_duplicate_error(tmp_db):
    rows = pd.DataFrame(
        {
            "vendor_name": ["Skip Co", "Skip Co", "Skip Co"],
            "po_number": ["NONE", "NONE", "PO-REAL-1"],
            "total_amount": [100, 200, 500],
            "issue_date": ["2026-01-01", "2026-01-02", "2026-01-03"],
        }
    )
    content = _xlsx_bytes({"purchase_orders": rows})
    vendor_first = _xlsx_bytes(
        {"vendors": pd.DataFrame({"vendor_id": ["V1"], "name": ["Skip Co"]})}
    )
    AdaptiveImporter().commit(vendor_first, "vendors.xlsx")

    result = AdaptiveImporter().commit(content, "pos.xlsx")
    assert result["valid"], result.get("errors")
    assert result["summary"]["purchase_orders"] == 1
    assert not any("duplicate po_number NONE" in e for e in result.get("errors", []))


def test_po_import_auto_creates_missing_vendor(tmp_db):
    rows = pd.DataFrame(
        {
            "vendor_name": ["Auto Vendor Inc"],
            "po_number": ["PO-AUTO-1"],
            "total_amount": [1200],
            "issue_date": ["2026-01-01"],
        }
    )
    content = _xlsx_bytes({"purchase_orders": rows})
    result = AdaptiveImporter().commit(content, "auto_vendor_po.xlsx")
    assert result["valid"], result.get("errors")
    assert result["summary"]["vendors"] >= 1
    assert result["summary"]["purchase_orders"] == 1
    po = repository.get_po("PO-AUTO-1")
    assert po is not None
