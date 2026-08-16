"""Vendor resolution outcomes for master data import."""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from app.services.import_normalize import safe_str
from app.services.master_data_importer import _next_vendor_id, _resolve_vendor_key
from app.services.vendor_identity import normalize_vendor_name


@dataclass
class VendorResolution:
    status: str  # existing | safe_create | ambiguous | blocked
    vendor_id: str | None = None
    vendor_name: str | None = None
    candidates: list[dict] = field(default_factory=list)
    message: str | None = None


def resolve_vendor_for_row(
    company_id: str,
    row: dict,
    vendor_by_id: dict,
    vendor_by_supplier: dict,
    vendor_by_tax: dict,
    vendor_by_norm: dict,
    fuzzy_threshold: float = 0.88,
) -> VendorResolution:
    """Resolve vendor for a PO or invoice row."""
    vendor_name = safe_str(row.get("vendor_name") or row.get("name"))
    supplier_code = safe_str(row.get("supplier_code"))
    tax_id = safe_str(row.get("tax_id"))
    vendor_id = safe_str(row.get("vendor_id"))
    resolve_row = {**row, "name": vendor_name or row.get("name")}

    if supplier_code and supplier_code in vendor_by_supplier:
        v = vendor_by_supplier[supplier_code]
        return VendorResolution("existing", v["vendor_id"], v["name"])

    if tax_id and tax_id in vendor_by_tax:
        v = vendor_by_tax[tax_id]
        return VendorResolution("existing", v["vendor_id"], v["name"])

    if vendor_id and vendor_id in vendor_by_id:
        v = vendor_by_id[vendor_id]
        return VendorResolution("existing", vendor_id, v["name"])

    if vendor_name:
        norm = normalize_vendor_name(vendor_name)
        if norm in vendor_by_norm:
            v = vendor_by_norm[norm]
            return VendorResolution("existing", v["vendor_id"], v["name"])

        fuzzy_matches: list[dict] = []
        for v in vendor_by_id.values():
            vnorm = v.get("normalized_name") or normalize_vendor_name(v.get("name", ""))
            ratio = SequenceMatcher(None, norm, vnorm).ratio()
            if ratio >= fuzzy_threshold:
                fuzzy_matches.append({**v, "_similarity": ratio})

        if len(fuzzy_matches) == 1:
            v = fuzzy_matches[0]
            return VendorResolution("existing", v["vendor_id"], v["name"])

        if len(fuzzy_matches) > 1:
            return VendorResolution(
                "ambiguous",
                None,
                vendor_name,
                candidates=fuzzy_matches,
                message=f"Vendor '{vendor_name}' matches multiple existing vendors",
            )

        vid, err = _resolve_vendor_key(
            company_id, resolve_row, vendor_by_id, vendor_by_supplier, vendor_by_tax, vendor_by_norm
        )
        if err:
            return VendorResolution("blocked", None, vendor_name, message=err)
        if vid:
            return VendorResolution("safe_create", vid, vendor_name)

    if vendor_id:
        return VendorResolution("safe_create", vendor_id, vendor_name or vendor_id)

    return VendorResolution("blocked", None, None, message="Missing vendor name and identifiers")
