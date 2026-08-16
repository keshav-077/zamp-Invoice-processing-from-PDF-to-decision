"""Deterministic row-level entity classification for master data import."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.pipeline.policy_loader import load_import_mapping
from app.services.import_normalize import normalize_po_reference, safe_float, safe_str
from app.services.import_profiler import normalize_header


@dataclass
class RowClassification:
    record_type: str
    confidence: float
    reasons: list[str] = field(default_factory=list)
    po_reference: str | None = None


RECORD_TYPE_TO_ENTITY = {
    "vendor": "vendor",
    "purchase_order": "po",
    "invoice_transaction": "invoice_transaction",
    "invoice_with_po_reference": "invoice_transaction",
    "line": "line",
    "grn": "grn",
    "reference": "reference",
    "unclassified": "unclassified",
}


def record_type_to_entity(record_type: str) -> str:
    return RECORD_TYPE_TO_ENTITY.get(record_type, "unclassified")


def _field_aliases(cfg: dict) -> dict[str, list[str]]:
    """Flatten entity field aliases from import_mapping config."""
    out: dict[str, list[str]] = {}
    for entity_spec in cfg.get("entities", {}).values():
        for canonical, aliases in entity_spec.get("fields", {}).items():
            out.setdefault(canonical, [])
            for a in aliases:
                if normalize_header(a) not in out[canonical]:
                    out[canonical].append(normalize_header(a))
    row_cfg = cfg.get("row_classification", {})
    for aliases in row_cfg.get("field_aliases", {}).values():
        for canonical, names in aliases.items():
            out.setdefault(canonical, [])
            for a in names:
                na = normalize_header(a)
                if na not in out[canonical]:
                    out[canonical].append(na)
    return out


def _row_values_by_canonical(raw_row: dict[str, Any], aliases: dict[str, list[str]]) -> dict[str, Any]:
    norm_row = {normalize_header(k): v for k, v in raw_row.items()}
    values: dict[str, Any] = {}
    for canonical, names in aliases.items():
        for name in names:
            if name in norm_row and safe_str(norm_row[name]):
                values[canonical] = norm_row[name]
                break
    # Preserve raw keys for sentinel PO detection
    if "po_number" in norm_row and "po_number" not in values:
        values["po_number"] = norm_row["po_number"]
    return values


def _has_any(values: dict, keys: list[str]) -> bool:
    for k in keys:
        v = values.get(k)
        if v is not None and safe_str(v):
            if k in ("invoice_total", "invoice_subtotal", "total_amount", "po_amount"):
                if safe_float(v) > 0:
                    return True
            else:
                return True
    return False


def _po_sentinels(cfg: dict) -> frozenset[str]:
    raw = cfg.get("row_classification", {}).get("po_sentinels", [])
    base = {"none", "n/a", "na", "null", "nil", "-", "nan", "missing"}
    return frozenset(base | {str(x).lower() for x in raw})


def classify_row(raw_row: dict[str, Any], explicit_record_type: str | None = None) -> RowClassification:
    """Classify a single row using deterministic signals from config."""
    cfg = load_import_mapping()
    aliases = _field_aliases(cfg)
    values = _row_values_by_canonical(raw_row, aliases)
    sentinels = _po_sentinels(cfg)

    if explicit_record_type:
        rt = normalize_header(explicit_record_type)
        flat = cfg.get("flat_record_types", {})
        for entity, types in flat.items():
            if rt in [normalize_header(t) for t in types]:
                mapped = {
                    "vendor": "vendor",
                    "po": "purchase_order",
                    "line": "line",
                    "grn": "grn",
                    "reference": "reference",
                }.get(entity, entity)
                po_ref = normalize_po_reference(
                    values.get("po_number") or values.get("po_reference"), sentinels
                )
                return RowClassification(
                    record_type=mapped,
                    confidence=1.0,
                    reasons=[f"explicit record_type={explicit_record_type}"],
                    po_reference=po_ref,
                )

    po_num_raw = values.get("po_number") or values.get("po_reference")
    po_ref = normalize_po_reference(po_num_raw, sentinels)

    rcfg = cfg.get("row_classification", {}).get("entities", {})
    invoice_req = rcfg.get("invoice_transaction", {}).get(
        "required_any", ["invoice_number", "secondary_id_number"]
    )
    invoice_sup = rcfg.get("invoice_transaction", {}).get(
        "supporting_any", ["invoice_total", "invoice_subtotal", "invoice_date"]
    )
    po_sup = rcfg.get("purchase_order", {}).get(
        "supporting_any", ["po_amount", "total_amount", "po_status", "issue_date", "po_date"]
    )

    has_invoice = _has_any(values, invoice_req) and _has_any(values, invoice_sup)
    has_po_support = _has_any(values, po_sup)
    has_vendor_id = _has_any(values, ["vendor_id", "tax_id", "supplier_code"])
    has_vendor_name = _has_any(values, ["name", "vendor_name"])
    has_line = _has_any(values, ["line_number"]) and po_ref
    has_grn = _has_any(values, ["grn_id"])
    has_ref = _has_any(values, ["reference_type", "reference_value"])

    if has_line:
        return RowClassification(
            record_type="line",
            confidence=0.85,
            reasons=["line_number and po reference"],
            po_reference=po_ref,
        )

    if po_ref and has_po_support and not has_invoice:
        return RowClassification(
            record_type="purchase_order",
            confidence=0.99,
            reasons=["valid po_number", "PO amount/status/date present"],
            po_reference=po_ref,
        )

    if has_invoice and po_ref:
        return RowClassification(
            record_type="invoice_with_po_reference",
            confidence=0.94,
            reasons=["invoice fields present", "po_reference present (unresolved)"],
            po_reference=po_ref,
        )

    if has_invoice:
        return RowClassification(
            record_type="invoice_transaction",
            confidence=0.92,
            reasons=["invoice fields present", "no valid PO reference"],
            po_reference=None,
        )

    if po_ref and has_po_support:
        return RowClassification(
            record_type="purchase_order",
            confidence=0.88,
            reasons=["valid po_number with PO supporting fields"],
            po_reference=po_ref,
        )

    if has_grn:
        return RowClassification(
            record_type="grn",
            confidence=0.85,
            reasons=["grn_id present"],
            po_reference=po_ref,
        )

    if has_ref:
        return RowClassification(
            record_type="reference",
            confidence=0.85,
            reasons=["reference fields present"],
            po_reference=po_ref,
        )

    # PO column present but sentinel (NONE/N/A) — still a PO row attempt, not vendor
    raw_po_val = safe_str(
        values.get("po_number") or raw_row.get("po_number") or raw_row.get("PO_NUMBER")
    )
    if raw_po_val and not po_ref and (has_po_support or has_vendor_name):
        return RowClassification(
            record_type="purchase_order",
            confidence=0.7,
            reasons=[f"po_number placeholder ({raw_po_val}) — not a valid PO"],
            po_reference=None,
        )

    if has_vendor_id or has_vendor_name:
        if not po_ref and not has_invoice:
            return RowClassification(
                record_type="vendor",
                confidence=0.8,
                reasons=["vendor identifiers without PO or invoice totals"],
                po_reference=None,
            )

    return RowClassification(
        record_type="unclassified",
        confidence=0.0,
        reasons=["insufficient classification signals"],
        po_reference=po_ref,
    )
