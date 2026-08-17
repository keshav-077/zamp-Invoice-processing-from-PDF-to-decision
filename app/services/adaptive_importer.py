"""
Adaptive master-data import: row-level classification, lossless staging,
entity-specific activation into vendor/PO/line/GRN/reference/source_records.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any

from app.db import repository
from app.db.transactions import db_transaction
from app.services import import_mapper, import_profiler
from app.services.import_normalize import safe_float, safe_str, valid_po_number
from app.services.json_safe import json_safe
from app.services.master_data_importer import _resolve_vendor_key
from app.services.row_classifier import (
    RowClassification,
    classify_row,
    record_type_to_entity,
)
from app.services.vendor_identity import normalize_vendor_name, ocr_vendor_aliases
from app.services.vendor_resolution import VendorResolution, resolve_vendor_for_row
from app.services.import_po_mirror import build_mirrored_po_row, ensure_vendor_for_mirror

logger = logging.getLogger(__name__)

DEFAULT_COMPANY_ID = "DEFAULT"

ACTIVATION_TYPES = (
    "vendor",
    "purchase_order",
    "invoice_transaction",
    "invoice_with_po_reference",
    "line",
    "grn",
    "reference",
    "unclassified",
)


def _empty_activation_summary() -> dict[str, dict[str, int]]:
    return {k: {"ready": 0, "skipped": 0, "review": 0, "blocked": 0} for k in ACTIVATION_TYPES}


def _mark_mappings_user_confirmed(sheet_info: dict) -> None:
    for mapping in sheet_info.get("column_mappings", []):
        if mapping.get("status") == "review" and mapping.get("canonical_field"):
            mapping["status"] = "auto"
            mapping["reason"] = "user_confirmed"


def _resolve_po_total(r: dict, metadata: dict) -> float:
    total = safe_float(r.get("total_amount"))
    if total > 0:
        return total
    for key in ("po_amount", "invoice_total", "invoice_subtotal", "total"):
        if key in metadata:
            total = safe_float(metadata[key])
            if total > 0:
                return total
        if key in r:
            total = safe_float(r[key])
            if total > 0:
                return total
    return 0.0


def _ensure_vendor_row(
    company_id: str,
    vendor_id: str,
    vendor_name: str,
    supplier_code: str,
    vendor_by_id: dict,
    vendor_by_supplier: dict,
    vendor_by_tax: dict,
    vendor_by_norm: dict,
    vendor_rows: list[dict],
    metadata: dict,
) -> None:
    norm = normalize_vendor_name(vendor_name)
    if vendor_id in vendor_by_id:
        return
    alias_set = set(ocr_vendor_aliases(vendor_name))
    vrow = {
        "vendor_id": vendor_id,
        "company_id": company_id,
        "name": vendor_name,
        "normalized_name": norm,
        "aliases_json": json.dumps(sorted(alias_set)),
        "tax_id": None,
        "supplier_code": supplier_code or None,
        "status": "active",
        "metadata_json": json.dumps(metadata),
    }
    vendor_rows.append(vrow)
    vendor_by_id[vendor_id] = vrow
    if vrow["supplier_code"]:
        vendor_by_supplier[vrow["supplier_code"]] = vrow
    vendor_by_norm[norm] = vrow


def _mappings_for_entity(
    entity: str,
    columns: list[str],
    profile: dict,
    sheet_mappings: list[dict] | None,
) -> list[dict]:
    saved = profile.get("saved_profile")
    if sheet_mappings:
        for sheet in sheet_mappings:
            if sheet.get("entity") == entity and sheet.get("column_mappings"):
                return sheet["column_mappings"]
    return import_mapper.propose_column_mappings(entity, columns, saved)


def _col_has_value(raw: dict, col: str) -> bool:
    val = raw.get(col)
    if val is None:
        return False
    if isinstance(val, float) and val != val:
        return False
    return bool(safe_str(val)) or isinstance(val, (int, float))


def _rows_from_profile(content: bytes, filename: str, profile: dict) -> list[dict]:
    """Materialize staged rows with per-row classification."""
    sheets = import_profiler.parse_workbook(content, filename)
    staged: list[dict] = []
    seen_row_keys: set[tuple[str, int]] = set()

    flat_mode = profile.get("flat_mode", False)
    processed_sheets: set[str] = set()

    if flat_mode:
        df = sheets.get("data")
        if df is not None and not df.empty:
            cols = [str(c) for c in df.columns]
            cols_lower = [import_profiler.normalize_header(c) for c in df.columns]
            has_record_type = "record_type" in cols_lower
            entity_profiles = {s.get("entity"): s for s in profile.get("sheets", [])}

            for row_idx, row in df.iterrows():
                raw = {str(k): json_safe(v) for k, v in row.to_dict().items()}
                explicit_rt = None
                if has_record_type:
                    rt_col = df.columns[cols_lower.index("record_type")]
                    explicit_rt = safe_str(row.get(rt_col))

                classification = classify_row(raw, explicit_record_type=explicit_rt or None)
                entity = record_type_to_entity(classification.record_type)
                sheet_mappings = entity_profiles.get(entity, {}).get("column_mappings")
                row_cols = [k for k in cols if _col_has_value(raw, k)]
                mappings = _mappings_for_entity(entity, row_cols, profile, None)
                if sheet_mappings:
                    mappings = sheet_mappings

                canonical, metadata = import_mapper.apply_mappings(raw, mappings)
                if classification.po_reference:
                    canonical["po_reference"] = classification.po_reference
                elif "po_reference" in canonical and not valid_po_number(canonical.get("po_reference")):
                    canonical.pop("po_reference", None)

                key = ("data", int(row_idx) if isinstance(row_idx, int) else len(staged))
                if key in seen_row_keys:
                    continue
                seen_row_keys.add(key)

                staged.append(
                    {
                        "entity": entity,
                        "record_type": classification.record_type,
                        "sheet_name": "data",
                        "row_index": key[1],
                        "raw_json": raw,
                        "canonical_json": canonical,
                        "metadata_json": metadata,
                        "classification_json": {
                            "record_type": classification.record_type,
                            "confidence": classification.confidence,
                            "reasons": classification.reasons,
                            "po_reference": classification.po_reference,
                        },
                    }
                )
        return staged

    for sheet_info in profile.get("sheets", []):
        sheet_key = sheet_info["sheet"]
        if sheet_key in processed_sheets:
            continue
        processed_sheets.add(sheet_key)

        df_key = sheet_key if sheet_key in sheets else "data"
        df = sheets.get(df_key)
        if df is None or df.empty:
            continue

        cols = [str(c) for c in df.columns]
        default_entity = sheet_info.get("entity") or "unknown"
        default_mappings = sheet_info.get("column_mappings") or import_mapper.propose_column_mappings(
            default_entity if default_entity != "unknown" else "po",
            cols,
            profile.get("saved_profile"),
        )

        for row_idx, row in df.iterrows():
            raw = {str(k): json_safe(v) for k, v in row.to_dict().items()}
            classification = classify_row(raw)
            entity = record_type_to_entity(classification.record_type)
            if entity == "unclassified" and default_entity not in ("unknown", "mixed"):
                entity = default_entity
                classification = RowClassification(
                    record_type=default_entity if default_entity != "po" else "purchase_order",
                    confidence=0.5,
                    reasons=[f"sheet default entity {default_entity}"],
                    po_reference=classification.po_reference,
                )
                if default_entity == "po":
                    classification.record_type = "purchase_order"

            mappings = (
                import_mapper.propose_column_mappings(
                    entity,
                    [k for k in cols if _col_has_value(raw, k)],
                    profile.get("saved_profile"),
                )
                if entity != default_entity
                else default_mappings
            )
            canonical, metadata = import_mapper.apply_mappings(raw, mappings)
            if classification.po_reference and entity == "invoice_transaction":
                canonical["po_reference"] = classification.po_reference
            elif "po_reference" in canonical and not valid_po_number(canonical.get("po_reference")):
                canonical.pop("po_reference", None)

            key = (sheet_key, int(row_idx) if isinstance(row_idx, int) else len(staged))
            if key in seen_row_keys:
                continue
            seen_row_keys.add(key)

            staged.append(
                {
                    "entity": entity,
                    "record_type": classification.record_type,
                    "sheet_name": sheet_key,
                    "row_index": key[1],
                    "raw_json": raw,
                    "canonical_json": canonical,
                    "metadata_json": metadata,
                    "classification_json": {
                        "record_type": classification.record_type,
                        "confidence": classification.confidence,
                        "reasons": classification.reasons,
                        "po_reference": classification.po_reference,
                    },
                }
            )
    return staged


def _build_column_map_from_confirmations(sheet_mappings: list[dict]) -> dict:
    column_map: dict[str, dict[str, str]] = {}
    for sheet in sheet_mappings:
        entity = sheet.get("entity")
        if not entity:
            continue
        entity_map: dict[str, str] = {}
        for m in sheet.get("column_mappings", []):
            if m.get("canonical_field") and m.get("status") != "metadata":
                entity_map[import_profiler.normalize_header(m["source_column"])] = m["canonical_field"]
        if entity_map:
            column_map[entity] = entity_map
    return column_map


def _issue(
    row_issues: list[dict],
    row: dict,
    status: str,
    message: str,
    severity: str = "warning",
) -> None:
    row_issues.append(
        {
            "row_index": row["row_index"],
            "sheet": row["sheet_name"],
            "record_type": row.get("record_type", row.get("entity")),
            "status": status,
            "severity": severity,
            "message": message,
        }
    )


class AdaptiveImporter:
    """Stage-first importer with row-level classification."""

    def preview(
        self,
        content: bytes,
        filename: str,
        company_id: str = DEFAULT_COMPANY_ID,
        confirmed_mappings: list[dict] | None = None,
    ) -> dict:
        return self._run(content, filename, company_id, commit=False, confirmed_mappings=confirmed_mappings)

    def commit(
        self,
        content: bytes,
        filename: str,
        company_id: str = DEFAULT_COMPANY_ID,
        confirmed_mappings: list[dict] | None = None,
    ) -> dict:
        import_id = uuid.uuid4().hex[:12]
        repository.create_master_data_import(
            import_id=import_id,
            company_id=company_id,
            filename=filename,
            status="processing",
        )
        try:
            result = self._run(
                content, filename, company_id, commit=True, confirmed_mappings=confirmed_mappings
            )
            repository.complete_master_data_import(
                import_id=import_id,
                status="completed" if result.get("valid") or result.get("partial_success") else "failed",
                summary=result.get("summary", {}),
                errors=result.get("errors", []),
                batch_id=result.get("batch_id"),
                file_checksum=result.get("file_checksum"),
                classification_summary=result.get("classification_summary"),
            )
            result["import_id"] = import_id
            return result
        except Exception as exc:
            from app.db.database import get_connection

            conn = get_connection()
            if hasattr(conn, "rollback"):
                conn.rollback()
            repository.complete_master_data_import(
                import_id=import_id,
                status="failed",
                summary={},
                errors=[str(exc)],
            )
            raise

    def activate_batch(self, batch_id: str, company_id: str = DEFAULT_COMPANY_ID) -> dict:
        batch = repository.get_staging_batch(batch_id)
        if not batch:
            return self._empty_result(["Batch not found"])
        if batch["company_id"] != company_id:
            return self._empty_result(["Company mismatch"])
        rows = repository.get_staging_rows(batch_id)
        return self._activate_rows(batch, rows, company_id)

    def _empty_result(self, errors: list[str]) -> dict:
        return {
            "valid": False,
            "partial_success": False,
            "errors": errors,
            "warnings": [],
            "summary": {},
            "classification_summary": _empty_activation_summary(),
            "row_issues": [],
            "preview": {},
        }

    def _run(
        self,
        content: bytes,
        filename: str,
        company_id: str,
        commit: bool,
        confirmed_mappings: list[dict] | None = None,
    ) -> dict:
        errors: list[str] = []
        warnings: list[str] = []
        summary = {
            "vendors": 0,
            "purchase_orders": 0,
            "po_lines": 0,
            "grn_records": 0,
            "references": 0,
            "source_records": 0,
            "metadata_fields": 0,
            "rows_analyzed": 0,
        }

        repository.ensure_company(company_id, company_id)

        try:
            profile = import_profiler.profile_workbook(content, filename)
        except Exception as exc:
            return {
                "valid": False,
                "partial_success": False,
                "errors": [str(exc)],
                "warnings": [],
                "summary": summary,
                "classification_summary": _empty_activation_summary(),
                "row_issues": [],
                "preview": {},
            }

        saved_profile = import_mapper.load_profile(company_id, profile["source_fingerprint"])
        profile["saved_profile"] = saved_profile

        entity_types = {"vendor", "po", "line", "grn", "reference", "invoice_transaction"}
        for sheet_info in profile["sheets"]:
            entity = sheet_info.get("entity") or "unknown"
            if entity == "unknown":
                warnings.append(f"Sheet '{sheet_info['sheet']}': could not infer entity type")
                sheet_info["column_mappings"] = []
                continue

            confirmed_sheet = None
            if confirmed_mappings:
                confirmed_sheet = next(
                    (
                        s
                        for s in confirmed_mappings
                        if s.get("sheet") == sheet_info["sheet"]
                        and s.get("entity") == sheet_info.get("entity")
                    ),
                    None,
                )
            if confirmed_sheet and confirmed_sheet.get("column_mappings"):
                sheet_info["column_mappings"] = confirmed_sheet["column_mappings"]
                if confirmed_mappings:
                    _mark_mappings_user_confirmed(sheet_info)
            else:
                sheet_info["column_mappings"] = import_mapper.propose_column_mappings(
                    entity if entity in entity_types else "po",
                    sheet_info["columns"],
                    saved_profile,
                )

        mappings_confirmed = bool(confirmed_mappings)
        review_needed = False if mappings_confirmed else any(
            m.get("status") == "review"
            for s in profile["sheets"]
            for m in s.get("column_mappings", [])
        )

        staged_rows = _rows_from_profile(content, filename, profile)
        summary["rows_analyzed"] = len(staged_rows)
        if not staged_rows:
            errors.append("No mappable rows detected in upload")

        existing = repository.get_staging_batch_by_checksum(company_id, profile["checksum"])
        if existing and existing.get("status") == "activated" and commit:
            warnings.append(
                f"Re-importing file previously activated as batch {existing['batch_id']}"
            )

        batch_id = uuid.uuid4().hex[:12]
        if commit:
            batch_id = repository.ensure_staging_batch(
                batch_id=batch_id,
                company_id=company_id,
                filename=filename,
                file_checksum=profile["checksum"],
                source_fingerprint=profile["source_fingerprint"],
                mapping_json={"sheets": profile["sheets"]},
                summary_json={"row_count": len(staged_rows)},
            )
            repository.insert_staging_rows(batch_id, staged_rows)
        else:
            batch_id = f"preview-{batch_id}"

        canonical = self._canonicalize(
            staged_rows, company_id, errors, warnings, summary, batch_id if commit else None
        )
        activation_summary = canonical["activation_summary"]
        row_issues = canonical["row_issues"]

        total_ready = sum(v["ready"] for v in activation_summary.values())
        total_blocked = sum(v["blocked"] for v in activation_summary.values())
        partial_success = total_ready > 0
        valid = total_ready > 0 and total_blocked == 0 and not review_needed

        if review_needed and not confirmed_mappings:
            valid = False
            warnings.append("Some column mappings need review before import")
        elif total_blocked > 0:
            valid = False
            warnings.append(f"Import blocked: {total_blocked} row(s) have blocking errors")
        elif mappings_confirmed and errors:
            warnings.append(f"{len(errors)} validation note(s) — see row issues")

        preview = {
            "profile": profile,
            "batch_id": batch_id,
            "review_needed": review_needed,
            "vendors": canonical["vendor_rows"][:5],
            "purchase_orders": canonical["po_rows"][:5],
            "po_lines": canonical["line_rows"][:10],
            "source_records": canonical["source_record_rows"][:5],
            "unknown_columns": self._unknown_columns(profile),
        }

        if (valid or partial_success) and commit and total_ready > 0 and (
            not review_needed or confirmed_mappings
        ):
            with db_transaction():
                if canonical["vendor_rows"]:
                    repository.upsert_vendors(canonical["vendor_rows"], commit=False)
                if canonical["po_rows"]:
                    repository.upsert_purchase_orders(canonical["po_rows"], commit=False)
                if canonical["line_rows"]:
                    repository.upsert_po_lines(canonical["line_rows"], commit=False)
                if canonical["grn_rows"]:
                    repository.upsert_grn_records(canonical["grn_rows"], commit=False)
                if canonical["ref_rows"]:
                    repository.upsert_po_references(canonical["ref_rows"], commit=False)
                if canonical["source_record_rows"]:
                    repository.upsert_source_records(canonical["source_record_rows"], commit=False)
                repository.mark_staging_batch_activated(batch_id)
                repository.update_staging_batch_validation(
                    batch_id,
                    {"classification_summary": activation_summary, "row_issues": row_issues[:100]},
                )

            if confirmed_mappings:
                column_map = _build_column_map_from_confirmations(confirmed_mappings)
                if column_map:
                    import_mapper.save_profile(
                        company_id, profile["source_fingerprint"], column_map, confirmed_by="user"
                    )
            elif saved_profile is None and not review_needed:
                column_map = _build_column_map_from_confirmations(profile["sheets"])
                if column_map:
                    import_mapper.save_profile(
                        company_id, profile["source_fingerprint"], column_map, confirmed_by="auto"
                    )

            logger.info("Adaptive import activated batch %s: %s", batch_id, summary)

        return json_safe(
            {
                "valid": valid,
                "partial_success": partial_success,
                "errors": errors,
                "warnings": warnings,
                "summary": summary,
                "classification_summary": activation_summary,
                "row_issues": row_issues[:100],
                "preview": preview,
                "batch_id": batch_id,
                "file_checksum": profile["checksum"],
                "review_needed": review_needed,
                "committed": (valid or partial_success) and commit and total_ready > 0,
            }
        )

    def _unknown_columns(self, profile: dict) -> list[dict]:
        unknown = []
        for sheet in profile.get("sheets", []):
            for m in sheet.get("column_mappings", []):
                if m.get("status") == "metadata":
                    unknown.append(
                        {
                            "sheet": sheet["sheet"],
                            "column": m["source_column"],
                            "entity": sheet.get("entity"),
                        }
                    )
        return unknown

    def _canonicalize(
        self,
        staged_rows: list[dict],
        company_id: str,
        errors: list[str],
        warnings: list[str],
        summary: dict,
        batch_id: str | None,
    ) -> dict:
        existing_vendors = repository.get_all_vendors(company_id=company_id)
        vendor_by_id = {v["vendor_id"]: v for v in existing_vendors}
        vendor_by_supplier = {v["supplier_code"]: v for v in existing_vendors if v.get("supplier_code")}
        vendor_by_tax = {v["tax_id"]: v for v in existing_vendors if v.get("tax_id")}
        vendor_by_norm = {v["normalized_name"]: v for v in existing_vendors}

        vendor_rows: list[dict] = []
        po_rows: list[dict] = []
        line_rows: list[dict] = []
        grn_rows: list[dict] = []
        ref_rows: list[dict] = []
        source_record_rows: list[dict] = []
        po_numbers_seen: set[str] = set()
        meta_count = 0
        activation_summary = _empty_activation_summary()
        row_issues: list[dict] = []

        def bump(rt: str, status: str) -> None:
            key = rt if rt in activation_summary else "unclassified"
            if status in activation_summary[key]:
                activation_summary[key][status] += 1

        for row in staged_rows:
            entity = row["entity"]
            record_type = row.get("record_type", entity)
            r = row["canonical_json"]
            metadata = row.get("metadata_json") or {}
            meta_count += len(metadata)
            classification = row.get("classification_json") or {}

            if entity == "unclassified" or record_type == "unclassified":
                bump("unclassified", "skipped")
                _issue(row_issues, row, "skipped", "Unclassified row — preserved in staging only")
                warnings.append(
                    f"Row {row['row_index']}: unclassified — preserved in staging only"
                )
                continue

            if entity == "vendor":
                vid, err = _resolve_vendor_key(
                    company_id, r, vendor_by_id, vendor_by_supplier, vendor_by_tax, vendor_by_norm
                )
                if err:
                    bump("vendor", "blocked")
                    errors.append(f"Vendor row {row['row_index']}: {err}")
                    _issue(row_issues, row, "blocked", err, "error")
                    continue
                name = safe_str(r.get("name"))
                if not name:
                    bump("vendor", "blocked")
                    errors.append(f"Vendor row {row['row_index']}: missing name")
                    _issue(row_issues, row, "blocked", "missing name", "error")
                    continue
                norm = normalize_vendor_name(name)
                aliases_raw = r.get("aliases", "")
                if isinstance(aliases_raw, str) and aliases_raw.startswith("["):
                    try:
                        aliases = json.loads(aliases_raw)
                    except json.JSONDecodeError:
                        aliases = [a.strip() for a in aliases_raw.split(",") if a.strip()]
                elif isinstance(aliases_raw, str) and aliases_raw:
                    aliases = [a.strip() for a in aliases_raw.split(",") if a.strip()]
                else:
                    aliases = []
                vrow = {
                    "vendor_id": vid,
                    "company_id": company_id,
                    "name": name,
                    "normalized_name": norm,
                    "aliases_json": json.dumps(aliases),
                    "tax_id": safe_str(r.get("tax_id")) or None,
                    "supplier_code": safe_str(r.get("supplier_code")) or None,
                    "status": safe_str(r.get("status")) or "active",
                    "metadata_json": json.dumps(metadata),
                }
                vendor_rows.append(vrow)
                vendor_by_id[vid] = vrow
                if vrow["supplier_code"]:
                    vendor_by_supplier[vrow["supplier_code"]] = vrow
                if vrow["tax_id"]:
                    vendor_by_tax[vrow["tax_id"]] = vrow
                vendor_by_norm[norm] = vrow
                bump("vendor", "ready")

            elif entity == "po" or record_type == "purchase_order":
                po_number = valid_po_number(r.get("po_number"))
                if not po_number:
                    bump("purchase_order", "skipped")
                    msg = (
                        f"No valid po_number (got {safe_str(r.get('po_number')) or 'empty'})"
                    )
                    _issue(row_issues, row, "skipped", msg)
                    warnings.append(f"Row {row['row_index']}: skipped — {msg}")
                    continue

                if po_number in po_numbers_seen:
                    bump("purchase_order", "blocked")
                    errors.append(f"PO row {row['row_index']}: duplicate po_number {po_number}")
                    _issue(row_issues, row, "blocked", f"duplicate po_number {po_number}", "error")
                    continue
                po_numbers_seen.add(po_number)

                resolution = resolve_vendor_for_row(
                    company_id, r, vendor_by_id, vendor_by_supplier, vendor_by_tax, vendor_by_norm
                )
                if resolution.status == "blocked":
                    bump("purchase_order", "blocked")
                    errors.append(f"PO row {row['row_index']}: {resolution.message}")
                    _issue(row_issues, row, "blocked", resolution.message or "vendor blocked", "error")
                    continue
                if resolution.status == "ambiguous":
                    bump("purchase_order", "review")
                    _issue(row_issues, row, "review", resolution.message or "ambiguous vendor")
                    warnings.append(f"PO row {row['row_index']}: {resolution.message}")
                    continue

                vendor_id = resolution.vendor_id
                vendor_name = resolution.vendor_name or safe_str(r.get("vendor_name"))
                if resolution.status == "safe_create" and vendor_id and vendor_name:
                    _ensure_vendor_row(
                        company_id,
                        vendor_id,
                        vendor_name,
                        safe_str(r.get("supplier_code")),
                        vendor_by_id,
                        vendor_by_supplier,
                        vendor_by_tax,
                        vendor_by_norm,
                        vendor_rows,
                        metadata,
                    )
                    warnings.append(
                        f"PO row {row['row_index']}: auto-created vendor {vendor_id} for '{vendor_name}'"
                    )

                if not vendor_id or vendor_id not in vendor_by_id:
                    bump("purchase_order", "blocked")
                    errors.append(f"PO row {row['row_index']}: could not resolve vendor")
                    _issue(row_issues, row, "blocked", "could not resolve vendor", "error")
                    continue

                total = _resolve_po_total(r, metadata)
                if total <= 0:
                    bump("purchase_order", "blocked")
                    errors.append(f"PO row {row['row_index']}: invalid total_amount")
                    _issue(row_issues, row, "blocked", "invalid total_amount", "error")
                    continue

                po_rows.append(
                    {
                        "po_number": po_number,
                        "company_id": company_id,
                        "vendor_id": vendor_id,
                        "vendor_name": vendor_name or vendor_by_id[vendor_id]["name"],
                        "total_amount": total,
                        "currency": safe_str(r.get("currency")) or "USD",
                        "status": safe_str(r.get("status")) or "open",
                        "po_type": safe_str(r.get("po_type")) or "standard",
                        "issue_date": safe_str(r.get("issue_date"))
                        or datetime.utcnow().strftime("%Y-%m-%d"),
                        "expiry_date": safe_str(r.get("expiry_date")) or None,
                        "received_amount": safe_float(r.get("received_amount")),
                        "previously_invoiced": safe_float(r.get("previously_invoiced")),
                        "metadata_json": json.dumps(metadata),
                    }
                )
                bump("purchase_order", "ready")

            elif entity == "invoice_transaction" or record_type in (
                "invoice_transaction",
                "invoice_with_po_reference",
            ):
                rt_key = record_type if record_type in activation_summary else "invoice_transaction"
                vendor_name = safe_str(r.get("vendor_name"))
                invoice_number = safe_str(r.get("invoice_number"))
                invoice_total = safe_float(r.get("invoice_total")) or safe_float(r.get("invoice_subtotal"))
                if not invoice_total and metadata:
                    invoice_total = safe_float(metadata.get("invoice_total")) or safe_float(
                        metadata.get("invoice_subtotal")
                    )

                if not vendor_name:
                    bump(rt_key, "blocked")
                    errors.append(f"Invoice row {row['row_index']}: missing vendor_name")
                    _issue(row_issues, row, "blocked", "missing vendor_name", "error")
                    continue
                if not invoice_number and invoice_total <= 0:
                    bump(rt_key, "blocked")
                    errors.append(
                        f"Invoice row {row['row_index']}: missing invoice_number and amount"
                    )
                    _issue(row_issues, row, "blocked", "missing invoice identifier/amount", "error")
                    continue

                resolution = resolve_vendor_for_row(
                    company_id, r, vendor_by_id, vendor_by_supplier, vendor_by_tax, vendor_by_norm
                )
                vendor_id = resolution.vendor_id if resolution.status != "ambiguous" else None
                if resolution.status == "ambiguous":
                    bump(rt_key, "review")
                    _issue(row_issues, row, "review", resolution.message or "ambiguous vendor")
                    warnings.append(f"Invoice row {row['row_index']}: {resolution.message}")
                elif resolution.status == "safe_create" and vendor_id:
                    _ensure_vendor_row(
                        company_id,
                        vendor_id,
                        vendor_name,
                        safe_str(r.get("supplier_code")),
                        vendor_by_id,
                        vendor_by_supplier,
                        vendor_by_tax,
                        vendor_by_norm,
                        vendor_rows,
                        metadata,
                    )

                po_ref = classification.get("po_reference") or safe_str(r.get("po_reference"))
                po_ref = valid_po_number(po_ref) if po_ref else None
                po_status = "unresolved" if po_ref else "not_applicable"
                rec_type = (
                    "invoice_with_po_reference"
                    if record_type == "invoice_with_po_reference" or po_ref
                    else "invoice_transaction"
                )

                source_record_id = uuid.uuid4().hex[:12]
                source_record_rows.append(
                    {
                        "source_record_id": source_record_id,
                        "company_id": company_id,
                        "record_type": rec_type,
                        "vendor_id": vendor_id,
                        "vendor_name": vendor_name,
                        "invoice_number": invoice_number or None,
                        "invoice_date": safe_str(r.get("invoice_date")) or None,
                        "invoice_total": invoice_total if invoice_total > 0 else None,
                        "invoice_subtotal": safe_float(r.get("invoice_subtotal")) or None,
                        "currency": safe_str(r.get("currency")) or "USD",
                        "po_reference": po_ref,
                        "po_reference_status": po_status,
                        "status": "active",
                        "import_batch_id": batch_id,
                        "source_row_index": row["row_index"],
                        "metadata_json": json.dumps(metadata),
                        "created_at": datetime.utcnow().isoformat(),
                    }
                )

                mirror_vendor_id = ensure_vendor_for_mirror(
                    company_id,
                    vendor_id,
                    vendor_name,
                    vendor_by_id,
                    vendor_by_supplier,
                    vendor_by_tax,
                    vendor_by_norm,
                    vendor_rows,
                    metadata,
                    _ensure_vendor_row,
                )
                if mirror_vendor_id and invoice_total > 0:
                    mirrored = build_mirrored_po_row(
                        source_record_id=source_record_id,
                        company_id=company_id,
                        vendor_id=mirror_vendor_id,
                        vendor_name=vendor_name,
                        invoice_total=invoice_total,
                        currency=safe_str(r.get("currency")) or "USD",
                        po_reference=po_ref,
                        import_batch_id=batch_id,
                        invoice_number=invoice_number or None,
                        invoice_date=safe_str(r.get("invoice_date")) or None,
                        po_numbers_seen=po_numbers_seen,
                    )
                    if mirrored:
                        po_numbers_seen.add(mirrored["po_number"])
                        po_rows.append(mirrored)
                        if not po_ref:
                            source_record_rows[-1]["po_reference"] = mirrored["po_number"]
                            source_record_rows[-1]["po_reference_status"] = "mirrored"

                bump(rt_key, "ready")

            elif entity == "line":
                po_number = safe_str(r.get("po_number"))
                if not po_number:
                    bump("line", "blocked")
                    errors.append(f"Line row {row['row_index']}: missing po_number")
                    _issue(row_issues, row, "blocked", "missing po_number", "error")
                    continue
                valid_po = po_numbers_seen | {
                    p["po_number"] for p in repository.get_all_open_pos(company_id)
                }
                if po_number not in valid_po and not any(p["po_number"] == po_number for p in po_rows):
                    bump("line", "blocked")
                    errors.append(f"Line row {row['row_index']}: PO {po_number} not found")
                    _issue(row_issues, row, "blocked", f"PO {po_number} not found", "error")
                    continue
                line_no = int(safe_float(r.get("line_number"), 0))
                if line_no <= 0:
                    bump("line", "blocked")
                    errors.append(f"Line row {row['row_index']}: invalid line_number")
                    _issue(row_issues, row, "blocked", "invalid line_number", "error")
                    continue
                qty = safe_float(r.get("quantity"))
                unit_price = safe_float(r.get("unit_price"))
                amount = safe_float(r.get("amount"), qty * unit_price)
                line_rows.append(
                    {
                        "company_id": company_id,
                        "po_number": po_number,
                        "line_number": line_no,
                        "description": safe_str(r.get("description")) or f"Line {line_no}",
                        "sku": safe_str(r.get("sku")) or None,
                        "quantity": qty,
                        "unit_price": unit_price,
                        "amount": amount,
                        "uom": safe_str(r.get("uom")) or "each",
                        "metadata_json": json.dumps(metadata),
                    }
                )
                bump("line", "ready")

            elif entity == "grn":
                grn_id = safe_str(r.get("grn_id")) or f"GRN-{uuid.uuid4().hex[:8]}"
                po_number = safe_str(r.get("po_number"))
                if not po_number:
                    bump("grn", "blocked")
                    errors.append(f"GRN row {row['row_index']}: missing po_number")
                    _issue(row_issues, row, "blocked", "missing po_number", "error")
                    continue
                grn_rows.append(
                    {
                        "grn_id": grn_id,
                        "company_id": company_id,
                        "po_number": po_number,
                        "received_date": safe_str(r.get("received_date"))
                        or datetime.utcnow().strftime("%Y-%m-%d"),
                        "received_amount": safe_float(r.get("received_amount")),
                        "status": safe_str(r.get("status")) or "confirmed",
                        "metadata_json": json.dumps(metadata),
                    }
                )
                bump("grn", "ready")

            elif entity == "reference":
                po_number = safe_str(r.get("po_number"))
                ref_type = safe_str(r.get("reference_type")) or "order_ref"
                ref_val = safe_str(r.get("reference_value"))
                if not po_number or not ref_val:
                    bump("reference", "blocked")
                    errors.append(
                        f"Reference row {row['row_index']}: missing po_number or reference_value"
                    )
                    _issue(row_issues, row, "blocked", "missing po_number or reference_value", "error")
                    continue
                ref_rows.append(
                    {
                        "company_id": company_id,
                        "po_number": po_number,
                        "reference_type": ref_type,
                        "reference_value": ref_val,
                        "normalized_value": re.sub(r"[\-\s\.\#]", "", ref_val.upper()),
                    }
                )
                bump("reference", "ready")

        summary["vendors"] = len(vendor_rows)
        summary["purchase_orders"] = len(po_rows)
        summary["po_lines"] = len(line_rows)
        summary["grn_records"] = len(grn_rows)
        summary["references"] = len(ref_rows)
        summary["source_records"] = len(source_record_rows)
        summary["metadata_fields"] = meta_count

        return {
            "vendor_rows": vendor_rows,
            "po_rows": po_rows,
            "line_rows": line_rows,
            "grn_rows": grn_rows,
            "ref_rows": ref_rows,
            "source_record_rows": source_record_rows,
            "activation_summary": activation_summary,
            "row_issues": row_issues,
        }

    def _activate_rows(self, batch: dict, rows: list[dict], company_id: str) -> dict:
        errors: list[str] = []
        warnings: list[str] = []
        summary = {
            "vendors": 0,
            "purchase_orders": 0,
            "po_lines": 0,
            "grn_records": 0,
            "references": 0,
            "source_records": 0,
        }
        canonical = self._canonicalize(
            rows, company_id, errors, warnings, summary, batch["batch_id"]
        )
        total_ready = sum(v["ready"] for v in canonical["activation_summary"].values())
        total_blocked = sum(v["blocked"] for v in canonical["activation_summary"].values())
        valid = total_ready > 0 and total_blocked == 0 and not errors

        if not valid and total_ready == 0:
            return {
                "valid": False,
                "partial_success": False,
                "errors": errors,
                "warnings": warnings,
                "summary": summary,
                "classification_summary": canonical["activation_summary"],
                "row_issues": canonical["row_issues"],
            }

        with db_transaction():
            if canonical["vendor_rows"]:
                repository.upsert_vendors(canonical["vendor_rows"], commit=False)
            if canonical["po_rows"]:
                repository.upsert_purchase_orders(canonical["po_rows"], commit=False)
            if canonical["line_rows"]:
                repository.upsert_po_lines(canonical["line_rows"], commit=False)
            if canonical["grn_rows"]:
                repository.upsert_grn_records(canonical["grn_rows"], commit=False)
            if canonical["ref_rows"]:
                repository.upsert_po_references(canonical["ref_rows"], commit=False)
            if canonical["source_record_rows"]:
                repository.upsert_source_records(canonical["source_record_rows"], commit=False)
            repository.mark_staging_batch_activated(batch["batch_id"])

        return {
            "valid": valid,
            "partial_success": total_ready > 0,
            "errors": errors,
            "warnings": warnings,
            "summary": summary,
            "classification_summary": canonical["activation_summary"],
            "row_issues": canonical["row_issues"],
            "batch_id": batch["batch_id"],
        }
