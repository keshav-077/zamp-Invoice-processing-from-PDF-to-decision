"""
Tests for Stage 2 — Line-Level Matching Engine
"""
import pytest
from app.pipeline.stage2.line_matcher import LineMatcher


MOCK_PO_LINES = [
    {"line_number": 1, "description": "Cloud Infrastructure Setup", "sku": "SVC-CLOUD-001",
     "quantity": 1, "unit_price": 2500, "amount": 2500, "uom": "each"},
    {"line_number": 2, "description": "API Integration Services", "sku": "SVC-API-002",
     "quantity": 3, "unit_price": 800, "amount": 2400, "uom": "each"},
    {"line_number": 3, "description": "Security Audit & Compliance Review", "sku": "SVC-SEC-003",
     "quantity": 1, "unit_price": 1200, "amount": 1200, "uom": "each"},
]


class TestExactMatch:
    def test_sku_match(self):
        inv_lines = [
            {"description": "SVC-CLOUD-001 Cloud Setup", "quantity": 1, "unit_price": 2500, "amount": 2500},
        ]
        lm = LineMatcher()
        result = lm.match_lines(inv_lines, MOCK_PO_LINES, "PO-TEST")
        assert len(result) == 1
        assert result[0].match_type == "exact"
        assert result[0].po_line == 1


class TestSemanticMatch:
    def test_description_similarity(self):
        inv_lines = [
            {"description": "Cloud Infrastructure Setup Service", "quantity": 1, "unit_price": 2500, "amount": 2500},
        ]
        lm = LineMatcher()
        result = lm.match_lines(inv_lines, MOCK_PO_LINES, "PO-TEST")
        assert len(result) == 1
        assert result[0].match_type in ("exact", "semantic")
        assert result[0].po_line == 1
        assert result[0].similarity_score > 0.3


class TestMultipleLines:
    def test_multiple_line_matching(self):
        inv_lines = [
            {"description": "Cloud Infrastructure Setup", "quantity": 1, "unit_price": 2500, "amount": 2500},
            {"description": "API Integration", "quantity": 3, "unit_price": 800, "amount": 2400},
            {"description": "Security Audit", "quantity": 1, "unit_price": 1200, "amount": 1200},
        ]
        lm = LineMatcher()
        result = lm.match_lines(inv_lines, MOCK_PO_LINES, "PO-TEST")
        assert len(result) == 3
        matched = [m for m in result if m.match_type != "unmatched"]
        assert len(matched) >= 2  # At least 2 should match


class TestNoMatch:
    def test_unmatched_line(self):
        inv_lines = [
            {"description": "Zebra feed quarterly", "quantity": 999, "unit_price": 0.01, "amount": 9.99},
        ]
        lm = LineMatcher()
        result = lm.match_lines(inv_lines, MOCK_PO_LINES, "PO-TEST")
        assert len(result) == 1
        # With zero token overlap and mismatched qty/price, score should be below threshold
        assert result[0].similarity_score < 0.3


class TestEmptyInputs:
    def test_no_invoice_lines(self):
        lm = LineMatcher()
        result = lm.match_lines([], MOCK_PO_LINES, "PO-TEST")
        assert result == []

    def test_no_po_lines(self):
        inv_lines = [
            {"description": "Some Service", "quantity": 1, "unit_price": 100, "amount": 100},
        ]
        lm = LineMatcher()
        result = lm.match_lines(inv_lines, [], "PO-TEST")
        assert len(result) == 1
        assert result[0].match_type == "unmatched"
