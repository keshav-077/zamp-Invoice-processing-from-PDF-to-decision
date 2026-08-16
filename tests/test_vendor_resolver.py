"""Vendor resolver — OCR/comma name variants."""

from unittest.mock import patch

from app.pipeline.stage2.vendor_resolver import VendorResolver


def test_harrington_comma_variant_resolves():
    resolver = VendorResolver()
    vendors = [
        {
            "vendor_id": "V001",
            "name": "Harrington Kline and Butler",
            "normalized_name": "HARRINGTON KLINE BUTLER",
            "aliases": ["Harrington, Kline and Butler"],
            "status": "active",
        }
    ]

    result = resolver._equivalent_name_match("Harrington, Kline and Butler", vendors)
    assert result is not None
    assert result.vendor_id == "V001"
    assert result.match_method == "equivalent"


@patch("app.pipeline.stage2.vendor_resolver.repository")
def test_resolve_comma_variant_against_master(mock_repo):
    mock_repo.get_all_vendors.return_value = [
        {
            "vendor_id": "V001",
            "name": "Harrington Kline and Butler",
            "normalized_name": "HARRINGTON KLINE BUTLER",
            "aliases": [],
            "status": "active",
        }
    ]
    resolver = VendorResolver()
    result = resolver.resolve("Harrington, Kline and Butler")
    assert result.vendor_id == "V001"
