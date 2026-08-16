"""
Tests for Stage 3: Vendor Validator
"""

import pytest
from app.pipeline.stage3.validation_context import ValidationContext
from app.pipeline.stage3.vendor_validator import validate_vendor


def _make_ctx(**overrides) -> ValidationContext:
    defaults = dict(
        document_id="DOC-TEST",
        vendor_name="Acme Corporation",
        matched_vendor_id="V001",
        vendor={
            "vendor_id": "V001",
            "name": "Acme Corporation",
            "status": "active",
        },
        vendor_status="active",
        vendor_ref="V001:v1",
        po={"vendor_id": "V001"},
    )
    defaults.update(overrides)
    return ValidationContext(**defaults)


class TestVendorStatus:
    def test_active_vendor_passes(self):
        ctx = _make_ctx()
        result = validate_vendor(ctx)
        assert result.status == "PASS"

    def test_inactive_vendor_fails(self):
        ctx = _make_ctx(
            vendor={"vendor_id": "V006", "name": "Inactive", "status": "inactive"},
            vendor_status="inactive",
        )
        result = validate_vendor(ctx)
        assert result.status == "FAIL"
        assert result.reason_code == "VENDOR_INELIGIBLE"

    def test_suspended_vendor_fails(self):
        ctx = _make_ctx(
            vendor={"vendor_id": "V099", "name": "Suspended Corp", "status": "suspended"},
            vendor_status="suspended",
        )
        result = validate_vendor(ctx)
        assert result.status == "FAIL"


class TestVendorAlignment:
    def test_vendor_po_match(self):
        ctx = _make_ctx()
        result = validate_vendor(ctx)
        assert result.status == "PASS"
        assert any("alignment confirmed" in e for e in result.evidence)

    def test_vendor_po_mismatch(self):
        ctx = _make_ctx(po={"vendor_id": "V002"})
        result = validate_vendor(ctx)
        assert result.status == "FLAG"
        assert result.reason_code == "VENDOR_REVIEW_REQUIRED"


class TestNoVendor:
    def test_no_vendor_data(self):
        ctx = _make_ctx(vendor=None)
        result = validate_vendor(ctx)
        assert result.status == "UNAVAILABLE"

    def test_non_po_workflow(self):
        ctx = _make_ctx(vendor=None, match_status="non_po_workflow")
        result = validate_vendor(ctx)
        assert result.status == "FLAG"
        assert result.reason_code == "VENDOR_NOT_VERIFIED"
