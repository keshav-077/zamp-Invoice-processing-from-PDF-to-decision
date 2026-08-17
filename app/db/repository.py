"""
InvoiceFlow AI — Database Repository

CRUD operations for invoice processing runs and Stage 2 PO matching.
All data is serialized as JSON for flexible schema evolution.
"""

import json
import logging
from datetime import datetime

from app.db.database import get_connection
from app.db.sql_dialect import build_upsert_sql, is_postgres
from app.models.pipeline import PipelineResult

logger = logging.getLogger(__name__)


def ensure_invoice_run_stub(
    document_id: str,
    filename: str,
    original_file_path: str = "",
    company_id: str = "DEFAULT",
) -> None:
    """
    Create a placeholder invoice_runs row before stage 2–5 child records.

    Postgres enforces FK constraints; SQLite does not unless PRAGMA foreign_keys=ON.
    The pipeline persists stage artifacts before the final save_run() upsert.
    """
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO invoice_runs (
            document_id, filename, status, upload_timestamp,
            original_file_path, company_id, workflow_state
        )
        VALUES (?, ?, 'processing', ?, ?, ?, 'processing')
        ON CONFLICT (document_id) DO NOTHING
        """,
        (
            document_id,
            filename,
            datetime.utcnow().isoformat(),
            original_file_path,
            company_id,
        ),
    )
    conn.commit()


def save_run(result: PipelineResult, company_id: str = "DEFAULT") -> None:
    """Save a complete pipeline result to the database."""
    conn = get_connection()
    columns = [
        "document_id",
        "filename",
        "status",
        "upload_timestamp",
        "processing_time_seconds",
        "pages_json",
        "extraction_json",
        "verification_json",
        "arithmetic_json",
        "reconciliation_json",
        "document_quality_score",
        "decision",
        "decision_explanation_json",
        "retry_count",
        "error_details",
        "original_file_path",
        "stage2_result_json",
        "stage2_status",
        "stage3_result_json",
        "stage3_status",
        "stage4_result_json",
        "stage4_status",
        "stage4_decision",
        "stage5_result_json",
        "stage5_status",
        "stage5_explanation_id",
        "company_id",
        "evidence_profile_json",
        "extraction_quality",
        "workflow_state",
    ]
    conn.execute(
        build_upsert_sql("invoice_runs", columns, ["document_id"]),
        (
            result.document_id,
            result.filename,
            result.status,
            result.upload_timestamp.isoformat(),
            result.processing_time_seconds,
            json.dumps([p.model_dump() for p in result.pages]),
            result.extraction.model_dump_json() if result.extraction else None,
            result.verification.model_dump_json() if result.verification else None,
            result.arithmetic.model_dump_json() if result.arithmetic else None,
            result.reconciliation.model_dump_json() if result.reconciliation else None,
            result.document_quality_score,
            result.decision,
            json.dumps(result.decision_explanation),
            result.retry_count,
            result.error_details,
            result.original_file_path,
            result.stage2_result.model_dump_json() if result.stage2_result else None,
            result.stage2_status,
            result.stage3_result.model_dump_json() if result.stage3_result else None,
            result.stage3_status,
            result.stage4_result.model_dump_json() if result.stage4_result else None,
            result.stage4_status,
            result.stage4_decision,
            result.stage5_result.model_dump_json() if result.stage5_result else None,
            result.stage5_status,
            result.stage5_explanation_id,
            company_id,
            result.evidence_profile.model_dump_json() if result.evidence_profile else None,
            result.extraction_quality.value if result.extraction_quality else "",
            result.workflow_state,
        ),
    )
    conn.commit()
    logger.info(f"Saved run: {result.document_id} ({result.status})")


def get_run(document_id: str) -> dict | None:
    """Retrieve a single run by document ID."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM invoice_runs WHERE document_id = ?",
        (document_id,),
    ).fetchone()

    if row is None:
        return None

    return _row_to_dict(row)


def list_runs(
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """List invoice runs with optional status filter and pagination."""
    conn = get_connection()

    if status_filter:
        rows = conn.execute(
            """
            SELECT * FROM invoice_runs
            WHERE status = ?
            ORDER BY upload_timestamp DESC
            LIMIT ? OFFSET ?
            """,
            (status_filter, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM invoice_runs
            ORDER BY upload_timestamp DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()

    return [_row_to_dict(row) for row in rows]


def get_stats() -> dict:
    """Get summary statistics of all invoice runs."""
    conn = get_connection()

    total = conn.execute("SELECT COUNT(*) FROM invoice_runs").fetchone()[0]

    status_counts = {}
    for row in conn.execute(
        "SELECT status, COUNT(*) as count FROM invoice_runs GROUP BY status"
    ).fetchall():
        status_counts[row["status"]] = row["count"]

    avg_time = conn.execute(
        "SELECT AVG(processing_time_seconds) FROM invoice_runs WHERE status != 'extraction_failed'"
    ).fetchone()[0]

    return {
        "total_invoices": total,
        "status_counts": status_counts,
        "stage1_passed": status_counts.get("stage1_passed", 0),
        "needs_human_review": status_counts.get("needs_human_review", 0),
        "extraction_failed": status_counts.get("extraction_failed", 0),
        "avg_processing_time": round(avg_time, 2) if avg_time else 0.0,
        "auto_approval_rate": (
            round(status_counts.get("stage1_passed", 0) / total * 100, 1)
            if total > 0
            else 0.0
        ),
    }


def _row_to_dict(row: object) -> dict:
    """Convert a sqlite3.Row to a dictionary with parsed JSON fields."""
    d = dict(row)

    # Parse JSON fields
    for json_field in [
        "pages_json",
        "extraction_json",
        "verification_json",
        "arithmetic_json",
        "reconciliation_json",
        "decision_explanation_json",
        "stage2_result_json",
        "stage3_result_json",
        "stage4_result_json",
        "stage5_result_json",
        "evidence_profile_json",
    ]:
        if d.get(json_field):
            try:
                d[json_field] = json.loads(d[json_field])
            except json.JSONDecodeError:
                pass

    return d


# ═══════════════════════════════════════════════════════════
# STAGE 2 — Vendor / PO / GRN Repository Methods
# ═══════════════════════════════════════════════════════════


def get_all_vendors(company_id: str = "DEFAULT") -> list[dict]:
    """Get all vendors from the Vendor Master."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM vendors WHERE company_id = ?",
        (company_id,),
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("aliases_json"):
            try:
                d["aliases"] = json.loads(d["aliases_json"])
            except json.JSONDecodeError:
                d["aliases"] = []
        else:
            d["aliases"] = []
        result.append(d)
    return result


def get_vendor_by_id(vendor_id: str, company_id: str = "DEFAULT") -> dict | None:
    """Get a vendor by vendor_id within company scope."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM vendors WHERE vendor_id = ? AND company_id = ?",
        (vendor_id, company_id),
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["aliases"] = json.loads(d.get("aliases_json", "[]"))
    return d


def get_vendor_by_tax_id(tax_id: str) -> dict | None:
    """Find vendor by tax ID / GSTIN / PAN."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM vendors WHERE tax_id = ?", (tax_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["aliases"] = json.loads(d.get("aliases_json", "[]"))
    return d


def search_vendors_by_name(normalized_name: str) -> list[dict]:
    """Search vendors by normalized name (partial match)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM vendors WHERE normalized_name LIKE ? AND status = 'active'",
        (f"%{normalized_name}%",),
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["aliases"] = json.loads(d.get("aliases_json", "[]"))
        result.append(d)
    return result


def get_po(po_number: str, company_id: str = "DEFAULT") -> dict | None:
    """Get a PO by number with its lines (company-scoped)."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM purchase_orders WHERE po_number = ? AND company_id = ?",
        (po_number, company_id),
    ).fetchone()
    if row is None:
        return None
    d = _parse_po_metadata(dict(row))
    d["lines"] = get_po_lines(po_number, company_id=company_id)
    return d


def get_po_lines(po_number: str, company_id: str = "DEFAULT") -> list[dict]:
    """Get all line items for a PO."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM po_lines WHERE po_number = ? AND company_id = ? ORDER BY line_number",
        (po_number, company_id),
    ).fetchall()
    return [dict(row) for row in rows]


def search_pos_by_number(po_number: str, company_id: str = "DEFAULT") -> list[dict]:
    """Search POs by exact or normalized number (company-scoped)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM purchase_orders WHERE po_number = ? AND company_id = ?",
        (po_number, company_id),
    ).fetchall()
    if rows:
        result = []
        for row in rows:
            d = dict(row)
            d["lines"] = get_po_lines(d["po_number"], company_id=company_id)
            result.append(d)
        return result

    normalized = po_number.upper().replace("-", "").replace(" ", "")
    all_pos = conn.execute(
        "SELECT * FROM purchase_orders WHERE company_id = ?",
        (company_id,),
    ).fetchall()
    result = []
    for row in all_pos:
        d = dict(row)
        po_norm = d["po_number"].upper().replace("-", "").replace(" ", "")
        if po_norm == normalized:
            d["lines"] = get_po_lines(d["po_number"], company_id=company_id)
            result.append(d)
    return result


def search_pos_by_vendor(vendor_id: str, status: str = "open", company_id: str = "DEFAULT") -> list[dict]:
    """Get all POs for a vendor with given status."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM purchase_orders WHERE vendor_id = ? AND status = ? AND company_id = ?",
        (vendor_id, status, company_id),
    ).fetchall()
    result = []
    for row in rows:
        d = _parse_po_metadata(dict(row))
        d["lines"] = get_po_lines(d["po_number"], company_id=company_id)
        result.append(d)
    return result


def _parse_po_metadata(d: dict) -> dict:
    if d.get("metadata_json"):
        try:
            d["metadata"] = json.loads(d["metadata_json"])
        except json.JSONDecodeError:
            d["metadata"] = {}
    else:
        d["metadata"] = {}
    d["_import_derived"] = bool(d.get("metadata", {}).get("import_derived"))
    return d


def _retrieval_method_for_po(po: dict, default_method: str) -> str:
    if po.get("_import_derived") or po.get("metadata", {}).get("import_derived"):
        return "import_derived"
    return default_method


def upsert_import_mirrored_po(row: dict, commit: bool = True) -> str:
    """Upsert a user-import mirrored PO row; returns po_number."""
    upsert_purchase_orders([row], commit=commit)
    return row["po_number"]


def get_all_open_pos(company_id: str = "DEFAULT") -> list[dict]:
    """Get all open POs."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM purchase_orders WHERE status = 'open' AND company_id = ?",
        (company_id,),
    ).fetchall()
    result = []
    for row in rows:
        d = _parse_po_metadata(dict(row))
        d["lines"] = get_po_lines(d["po_number"], company_id=company_id)
        result.append(d)
    return result


def get_grn_for_po(po_number: str, company_id: str = "DEFAULT") -> list[dict]:
    """Get GRN records for a PO."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM grn_records WHERE po_number = ? AND company_id = ?",
        (po_number, company_id),
    ).fetchall()
    return [dict(row) for row in rows]


def update_po_invoiced_amount(po_number: str, invoice_amount: float) -> None:
    """Update the previously_invoiced amount for a PO."""
    conn = get_connection()
    conn.execute(
        "UPDATE purchase_orders SET previously_invoiced = previously_invoiced + ? WHERE po_number = ?",
        (invoice_amount, po_number),
    )
    conn.commit()


def save_match_result(document_id: str, match_status: str, match_package_json: str) -> None:
    """Save a Stage 2 match result to the audit trail."""
    conn = get_connection()
    conn.execute(
        build_upsert_sql(
            "po_match_results",
            ["document_id", "match_status", "match_package_json", "matched_at"],
            ["document_id"],
        ),
        (document_id, match_status, match_package_json, datetime.utcnow().isoformat()),
    )
    conn.commit()
    logger.info(f"Saved match result: {document_id} ({match_status})")


def get_match_result(document_id: str) -> dict | None:
    """Retrieve the latest Stage 2 match result for a document."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM po_match_results WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def update_stage2_match(document_id: str, stage2_status: str, stage2_result_json: str) -> None:
    """Update Stage 2 fields on an invoice run without a full pipeline re-run."""
    conn = get_connection()
    conn.execute(
        """
        UPDATE invoice_runs SET stage2_status = ?, stage2_result_json = ?
        WHERE document_id = ?
        """,
        (stage2_status, stage2_result_json, document_id),
    )
    conn.commit()


# ═══════════════════════════════════════════════════════════
# STAGE 3 — Validation Run Repository Methods
# ═══════════════════════════════════════════════════════════


def save_validation_run(
    validation_run_id: str,
    document_id: str,
    overall_state: str,
    report_json: str,
    reason_codes_json: str = "[]",
    checks_json: str | None = None,
    controls_json: str = "[]",
    evidence_json: str = "[]",
    fraud_signals_json: str = "[]",
    policy_version: str = "AP-2026.08.1",
    source_snapshots_json: str | None = None,
    started_at: str = "",
    completed_at: str = "",
    parent_run_id: str | None = None,
    trigger: str = "initial",
) -> None:
    """Save a Stage 3 validation run to the audit trail."""
    conn = get_connection()
    vr_columns = [
        "validation_run_id",
        "document_id",
        "processing_state",
        "overall_state",
        "reason_codes_json",
        "checks_json",
        "controls_json",
        "evidence_json",
        "fraud_signals_json",
        "policy_version",
        "source_snapshots_json",
        "started_at",
        "completed_at",
        "parent_run_id",
        "trigger",
        "report_json",
    ]
    conn.execute(
        build_upsert_sql("validation_runs", vr_columns, ["validation_run_id"]),
        (
            validation_run_id, document_id, "COMPLETED", overall_state,
            reason_codes_json, checks_json, controls_json, evidence_json,
            fraud_signals_json, policy_version, source_snapshots_json,
            started_at, completed_at, parent_run_id, trigger, report_json,
        ),
    )
    conn.commit()
    logger.info(f"Saved validation run: {validation_run_id} ({overall_state})")


def get_validation_history(document_id: str) -> list[dict]:
    """Get all validation runs for an invoice (immutable history)."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT * FROM validation_runs
        WHERE document_id = ?
        ORDER BY started_at DESC
        """,
        (document_id,),
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        for json_field in [
            "reason_codes_json", "checks_json", "controls_json",
            "evidence_json", "fraud_signals_json", "source_snapshots_json",
            "report_json",
        ]:
            if d.get(json_field):
                try:
                    d[json_field] = json.loads(d[json_field])
                except json.JSONDecodeError:
                    pass
        result.append(d)
    return result


def get_prior_invoices_for_duplicate_check(
    vendor_name: str | None = None,
    invoice_number: str | None = None,
    amount: float | None = None,
) -> list[dict]:
    """Find prior invoices for duplicate detection."""
    conn = get_connection()
    results = []

    if invoice_number and vendor_name:
        # Exact duplicate: same vendor + invoice number
        rows = conn.execute(
            """
            SELECT document_id, filename, status, extraction_json,
                   upload_timestamp, stage3_status, stage4_decision
            FROM invoice_runs
            WHERE extraction_json LIKE ? AND extraction_json LIKE ?
            ORDER BY upload_timestamp DESC
            LIMIT 20
            """,
            (f'%{invoice_number}%', f'%{vendor_name}%'),
        ).fetchall()
        for row in rows:
            d = dict(row)
            if d.get("extraction_json"):
                try:
                    d["extraction_json"] = json.loads(d["extraction_json"])
                except json.JSONDecodeError:
                    pass
            results.append(d)

    return results


# ═══════════════════════════════════════════════════════════
# STAGE 4 — Decision Record Repository Methods
# ═══════════════════════════════════════════════════════════


def save_decision_record(
    decision_id: str,
    document_id: str,
    validation_run_id: str,
    decision: str,
    decision_substate: str,
    record_json: str,
    reason_codes_json: str = "[]",
    rules_json: str | None = None,
    policy_json: str | None = None,
    authority_json: str | None = None,
    routing_json: str | None = None,
    trace_json: str | None = None,
    evidence_refs_json: str = "[]",
    evidence_summary_json: str = "[]",
    decided_at: str = "",
    engine_version: str = "stage4-v2.0",
    processing_time_seconds: float = 0.0,
) -> None:
    """Save a Stage 4 decision record to the audit trail."""
    conn = get_connection()
    dec_columns = [
        "decision_id",
        "document_id",
        "validation_run_id",
        "decision",
        "decision_substate",
        "reason_codes_json",
        "rules_json",
        "policy_json",
        "authority_json",
        "routing_json",
        "trace_json",
        "evidence_refs_json",
        "evidence_summary_json",
        "decided_at",
        "engine_version",
        "processing_time_seconds",
        "record_json",
    ]
    conn.execute(
        build_upsert_sql("decision_records", dec_columns, ["decision_id"]),
        (
            decision_id, document_id, validation_run_id, decision, decision_substate,
            reason_codes_json, rules_json, policy_json, authority_json, routing_json,
            trace_json, evidence_refs_json, evidence_summary_json, decided_at,
            engine_version, processing_time_seconds, record_json,
        ),
    )
    conn.commit()
    logger.info(f"Saved decision: {decision_id} ({decision}/{decision_substate})")


def get_decision_history(document_id: str) -> list[dict]:
    """Get all decision records for an invoice (immutable history)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM decision_records WHERE document_id = ? ORDER BY decided_at DESC",
        (document_id,),
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        for json_field in [
            "reason_codes_json", "rules_json", "policy_json",
            "authority_json", "routing_json", "trace_json",
            "evidence_refs_json", "evidence_summary_json", "record_json",
        ]:
            if d.get(json_field):
                try:
                    d[json_field] = json.loads(d[json_field])
                except json.JSONDecodeError:
                    pass
        result.append(d)
    return result


def get_decision_by_id(decision_id: str) -> dict | None:
    """Get a single decision record by ID."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM decision_records WHERE decision_id = ?",
        (decision_id,),
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    for json_field in [
        "reason_codes_json", "rules_json", "policy_json",
        "authority_json", "routing_json", "trace_json",
        "evidence_refs_json", "evidence_summary_json", "record_json",
    ]:
        if d.get(json_field):
            try:
                d[json_field] = json.loads(d[json_field])
            except json.JSONDecodeError:
                pass
    return d


# ═══════════════════════════════════════════════════════════
# STAGE 5 — Explanation & Audit Ledger Repository Methods
# ═══════════════════════════════════════════════════════════


def save_explanation(
    explanation_id: str,
    tenant_id: str,
    decision_id: str,
    invoice_id: str,
    explanation_status: str,
    snapshot_json: str,
    generated_at: str,
    narrative_json: str | None = None,
    rule_trace_json: str | None = None,
    routing_json: str | None = None,
    authority_json: str | None = None,
    control_verification_json: str | None = None,
    evidence_refs_json: str = "[]",
    evidence_summary_json: str = "[]",
    gaps_json: str = "[]",
    upstream_artifacts_json: str = "[]",
    policy_version: str = "",
    policy_hash: str = "",
    decision_outcome: str = "",
    decision_substate: str = "",
    integrity_json: str | None = None,
    sampling_json: str | None = None,
    engine_version: str = "stage5-v3.0",
    processing_time_seconds: float = 0.0,
) -> None:
    """Save a Stage 5 explanation snapshot."""
    conn = get_connection()
    exp_columns = [
        "explanation_id",
        "tenant_id",
        "decision_id",
        "invoice_id",
        "explanation_status",
        "narrative_json",
        "rule_trace_json",
        "routing_json",
        "authority_json",
        "control_verification_json",
        "evidence_refs_json",
        "evidence_summary_json",
        "gaps_json",
        "upstream_artifacts_json",
        "policy_version",
        "policy_hash",
        "decision_outcome",
        "decision_substate",
        "integrity_json",
        "sampling_json",
        "snapshot_json",
        "generated_at",
        "engine_version",
        "processing_time_seconds",
    ]
    conn.execute(
        build_upsert_sql("explanation_snapshots", exp_columns, ["explanation_id"]),
        (
            explanation_id, tenant_id, decision_id, invoice_id,
            explanation_status, narrative_json, rule_trace_json,
            routing_json, authority_json, control_verification_json,
            evidence_refs_json, evidence_summary_json, gaps_json,
            upstream_artifacts_json, policy_version, policy_hash,
            decision_outcome, decision_substate, integrity_json,
            sampling_json, snapshot_json, generated_at, engine_version,
            processing_time_seconds,
        ),
    )
    conn.commit()
    logger.info(f"Saved explanation: {explanation_id} ({explanation_status})")


def get_explanation(document_id: str) -> dict | None:
    """Get the latest explanation for an invoice."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM explanation_snapshots WHERE invoice_id = ? ORDER BY generated_at DESC LIMIT 1",
        (document_id,),
    ).fetchone()
    if row is None:
        return None
    return _parse_explanation_row(row)


def get_explanation_history(document_id: str) -> list[dict]:
    """Get all explanations for an invoice."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM explanation_snapshots WHERE invoice_id = ? ORDER BY generated_at DESC",
        (document_id,),
    ).fetchall()
    return [_parse_explanation_row(row) for row in rows]


def get_explanation_by_decision(decision_id: str) -> dict | None:
    """Get explanation by decision ID."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM explanation_snapshots WHERE decision_id = ? LIMIT 1",
        (decision_id,),
    ).fetchone()
    if row is None:
        return None
    return _parse_explanation_row(row)


def _parse_explanation_row(row) -> dict:
    """Parse an explanation row with JSON fields."""
    d = dict(row)
    for json_field in [
        "narrative_json", "rule_trace_json", "routing_json", "authority_json",
        "control_verification_json", "evidence_refs_json", "evidence_summary_json",
        "gaps_json", "upstream_artifacts_json", "integrity_json",
        "sampling_json", "snapshot_json", "human_actions_json",
    ]:
        if d.get(json_field):
            try:
                d[json_field] = json.loads(d[json_field])
            except json.JSONDecodeError:
                pass
    return d


def append_audit_event(
    tenant_id: str,
    event_type: str,
    aggregate_id: str,
    content_hash: str,
    previous_hash: str = "GENESIS",
    explanation_id: str = "",
    decision_id: str = "",
    invoice_id: str = "",
    event_data_json: str | None = None,
    actor_id: str = "system",
    created_at: str = "",
) -> int:
    """Append an entry to the hash-chained audit ledger. Returns ledger_sequence."""
    conn = get_connection()
    params = (
        tenant_id, event_type, aggregate_id, explanation_id, decision_id,
        invoice_id, content_hash, previous_hash, event_data_json,
        actor_id, created_at,
    )
    if is_postgres():
        row = conn.execute(
            """
            INSERT INTO audit_ledger
            (tenant_id, event_type, aggregate_id, explanation_id, decision_id,
             invoice_id, content_hash, previous_hash, event_data_json,
             actor_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING ledger_sequence
            """,
            params,
        ).fetchone()
        conn.commit()
        sequence = int(row["ledger_sequence"]) if row else 0
    else:
        cursor = conn.execute(
            """
            INSERT INTO audit_ledger
            (tenant_id, event_type, aggregate_id, explanation_id, decision_id,
             invoice_id, content_hash, previous_hash, event_data_json,
             actor_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            params,
        )
        conn.commit()
        sequence = cursor.lastrowid
    logger.info(f"Audit ledger: seq={sequence} type={event_type} id={aggregate_id}")
    return sequence


def get_audit_chain(limit: int = 100) -> list[dict]:
    """Get the latest audit ledger entries."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM audit_ledger ORDER BY ledger_sequence DESC LIMIT ?",
        (limit,),
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("event_data_json"):
            try:
                d["event_data_json"] = json.loads(d["event_data_json"])
            except json.JSONDecodeError:
                pass
        result.append(d)
    return result


def get_last_audit_hash() -> str:
    """Get the content_hash of the last audit ledger entry."""
    conn = get_connection()
    row = conn.execute(
        "SELECT content_hash FROM audit_ledger ORDER BY ledger_sequence DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return "GENESIS"
    return row["content_hash"]


# ═══════════════════════════════════════════════════════════
# Enterprise — PO Confirmations, Review Items, Feedback
# ═══════════════════════════════════════════════════════════


def save_po_confirmation(
    document_id: str,
    chosen_po_number: str | None,
    confirmed_by: str,
    notes: str,
    action: str,
    suggested_snapshot_json: str | None = None,
) -> None:
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO po_confirmations
        (document_id, suggested_snapshot_json, chosen_po_number, confirmed_by, notes, action, confirmed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document_id,
            suggested_snapshot_json,
            chosen_po_number,
            confirmed_by,
            notes,
            action,
            datetime.utcnow().isoformat(),
        ),
    )
    if chosen_po_number:
        conn.execute(
            "UPDATE invoice_runs SET confirmed_po_number = ? WHERE document_id = ?",
            (chosen_po_number, document_id),
        )
    conn.commit()


def get_po_confirmations(document_id: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM po_confirmations WHERE document_id = ? ORDER BY confirmed_at DESC",
        (document_id,),
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("suggested_snapshot_json"):
            try:
                d["suggested_snapshot_json"] = json.loads(d["suggested_snapshot_json"])
            except json.JSONDecodeError:
                pass
        result.append(d)
    return result


def save_review_work_item(item) -> None:
    from app.models.review import ReviewWorkItem

    if not isinstance(item, ReviewWorkItem):
        item = ReviewWorkItem.model_validate(item)
    conn = get_connection()
    rw_columns = [
        "work_item_id",
        "document_id",
        "queue",
        "reason_codes_json",
        "priority",
        "sla_due_at",
        "status",
        "assigned_to",
        "stage1_status",
        "stage2_status",
        "stage4_decision",
        "created_at",
        "updated_at",
    ]
    conn.execute(
        build_upsert_sql("review_work_items", rw_columns, ["work_item_id"]),
        (
            item.work_item_id,
            item.document_id,
            item.queue,
            json.dumps(item.reason_codes),
            item.priority,
            item.sla_due_at,
            item.status,
            item.assigned_to,
            item.stage1_status,
            item.stage2_status,
            item.stage4_decision,
            item.created_at,
            item.updated_at,
        ),
    )
    conn.commit()


def list_review_work_items(
    queue: str | None = None,
    status: str = "open",
    limit: int = 50,
) -> list[dict]:
    conn = get_connection()
    if queue:
        rows = conn.execute(
            """
            SELECT * FROM review_work_items
            WHERE queue = ? AND status = ?
            ORDER BY sla_due_at ASC LIMIT ?
            """,
            (queue, status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM review_work_items
            WHERE status = ?
            ORDER BY sla_due_at ASC LIMIT ?
            """,
            (status, limit),
        ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("reason_codes_json"):
            try:
                d["reason_codes"] = json.loads(d["reason_codes_json"])
            except json.JSONDecodeError:
                d["reason_codes"] = []
        result.append(d)
    return result


def append_human_action(document_id: str, action) -> None:
    conn = get_connection()
    row = conn.execute(
        "SELECT human_actions_json FROM explanation_snapshots WHERE invoice_id = ? ORDER BY generated_at DESC LIMIT 1",
        (document_id,),
    ).fetchone()
    actions = []
    if row and row["human_actions_json"]:
        try:
            actions = json.loads(row["human_actions_json"])
        except json.JSONDecodeError:
            actions = []
    actions.append(action.model_dump())
    conn.execute(
        """
        UPDATE explanation_snapshots SET human_actions_json = ?
        WHERE invoice_id = ? AND explanation_id = (
            SELECT explanation_id FROM explanation_snapshots
            WHERE invoice_id = ? ORDER BY generated_at DESC LIMIT 1
        )
        """,
        (json.dumps(actions), document_id, document_id),
    )
    conn.commit()


def save_extraction_feedback(
    document_id: str,
    vendor_id: str,
    field_name: str,
    original_value: str | None,
    corrected_value: str,
    actor_id: str,
) -> None:
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO extraction_feedback
        (document_id, vendor_id, field_name, original_value, corrected_value, actor_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document_id,
            vendor_id,
            field_name,
            original_value,
            corrected_value,
            actor_id,
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()


def get_vendor_profile(vendor_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT profile_json FROM vendor_profiles WHERE vendor_id = ?",
        (vendor_id,),
    ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["profile_json"])
    except json.JSONDecodeError:
        return None


def save_vendor_profile(vendor_id: str, profile: dict) -> None:
    conn = get_connection()
    conn.execute(
        build_upsert_sql(
            "vendor_profiles",
            ["vendor_id", "profile_json", "updated_at"],
            ["vendor_id"],
        ),
        (vendor_id, json.dumps(profile), datetime.utcnow().isoformat()),
    )
    conn.commit()


def get_exception_analytics() -> dict:
    conn = get_connection()
    residual_rows = conn.execute(
        """
        SELECT COUNT(*) FROM invoice_runs
        WHERE reconciliation_json LIKE '%residual_review%'
        """
    ).fetchone()[0]
    review_reasons = conn.execute(
        """
        SELECT reason_codes_json, COUNT(*) as cnt FROM review_work_items
        GROUP BY reason_codes_json ORDER BY cnt DESC LIMIT 10
        """
    ).fetchall()
    po_confirmed = conn.execute(
        "SELECT COUNT(*) FROM po_confirmations WHERE action = 'confirm'"
    ).fetchone()[0]
    po_rejected = conn.execute(
        "SELECT COUNT(*) FROM po_confirmations WHERE action = 'reject'"
    ).fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM invoice_runs").fetchone()[0]
    passed = conn.execute(
        "SELECT COUNT(*) FROM invoice_runs WHERE status = 'stage1_passed'"
    ).fetchone()[0]
    return {
        "residual_review_count": residual_rows,
        "review_reason_breakdown": [dict(r) for r in review_reasons],
        "po_suggestion_acceptance_rate": (
            round(po_confirmed / (po_confirmed + po_rejected) * 100, 1)
            if (po_confirmed + po_rejected) > 0
            else 0.0
        ),
        "auto_pass_rate": round(passed / total * 100, 1) if total else 0.0,
        "total_processed": total,
    }


def update_run_after_correction(
    document_id: str,
    extraction,
    reconciliation,
    arithmetic,
    status: str,
    decision_explanation: list[str],
    stage2_result,
    stage2_status: str,
    stage3_status: str,
    stage4_decision: str,
) -> None:
    conn = get_connection()
    conn.execute(
        """
        UPDATE invoice_runs SET
            extraction_json = ?,
            reconciliation_json = ?,
            arithmetic_json = ?,
            status = ?,
            decision_explanation_json = ?,
            stage2_result_json = ?,
            stage2_status = ?,
            stage3_status = ?,
            stage4_decision = ?
        WHERE document_id = ?
        """,
        (
            extraction.model_dump_json(),
            reconciliation.model_dump_json(),
            arithmetic.model_dump_json(),
            status,
            json.dumps(decision_explanation),
            stage2_result.model_dump_json(),
            stage2_status,
            stage3_status,
            stage4_decision,
            document_id,
        ),
    )
    conn.commit()


def update_run_after_rerun(
    document_id: str,
    extraction,
    reconciliation,
    arithmetic,
    status: str,
    decision_explanation: list[str],
    stage2_result,
    stage2_status: str,
    stage3_status: str,
    stage4_decision: str,
    stage5_status: str = "",
) -> None:
    """Update invoice run after a full Stages 2–5 re-run."""
    conn = get_connection()
    conn.execute(
        """
        UPDATE invoice_runs SET
            extraction_json = ?,
            reconciliation_json = ?,
            arithmetic_json = ?,
            status = ?,
            decision_explanation_json = ?,
            stage2_result_json = ?,
            stage2_status = ?,
            stage3_status = ?,
            stage4_decision = ?,
            stage5_status = ?
        WHERE document_id = ?
        """,
        (
            extraction.model_dump_json(),
            reconciliation.model_dump_json(),
            arithmetic.model_dump_json(),
            status,
            json.dumps(decision_explanation),
            stage2_result.model_dump_json(),
            stage2_status,
            stage3_status,
            stage4_decision,
            stage5_status,
            document_id,
        ),
    )
    conn.commit()


def complete_review_work_item(work_item_id: str) -> None:
    """Close a review work item after human action."""
    conn = get_connection()
    conn.execute(
        """
        UPDATE review_work_items
        SET status = 'completed', updated_at = ?
        WHERE work_item_id = ?
        """,
        (datetime.utcnow().isoformat(), work_item_id),
    )
    conn.commit()


# ═══════════════════════════════════════════════════════════
# Processing Jobs
# ═══════════════════════════════════════════════════════════


def save_processing_job(
    job_id: str,
    filename: str,
    blob_url: str,
    storage_key: str,
    status: str,
    stage_status: dict,
    created_at: str,
    updated_at: str,
    document_id: str = "",
) -> None:
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO processing_jobs
        (job_id, document_id, filename, blob_url, storage_key, status,
         stage_status_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            document_id,
            filename,
            blob_url,
            storage_key,
            status,
            json.dumps(stage_status),
            created_at,
            updated_at,
        ),
    )
    conn.commit()


def get_processing_job(job_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM processing_jobs WHERE job_id = ?",
        (job_id,),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    if d.get("stage_status_json"):
        try:
            d["stage_status"] = json.loads(d["stage_status_json"])
        except json.JSONDecodeError:
            d["stage_status"] = {}
    return d


def update_processing_job(
    job_id: str,
    *,
    status: str | None = None,
    document_id: str | None = None,
    stage_status: dict | None = None,
    error_message: str | None = None,
) -> None:
    job = get_processing_job(job_id)
    if not job:
        return
    conn = get_connection()
    conn.execute(
        """
        UPDATE processing_jobs SET
            status = ?,
            document_id = ?,
            stage_status_json = ?,
            error_message = ?,
            updated_at = ?
        WHERE job_id = ?
        """,
        (
            status or job["status"],
            document_id if document_id is not None else job.get("document_id", ""),
            json.dumps(stage_status if stage_status is not None else job.get("stage_status", {})),
            error_message if error_message is not None else job.get("error_message", ""),
            datetime.utcnow().isoformat(),
            job_id,
        ),
    )
    conn.commit()


def update_po_previously_invoiced(po_number: str, amount: float) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE purchase_orders SET previously_invoiced = ? WHERE po_number = ?",
        (amount, po_number),
    )
    conn.commit()


# ═══════════════════════════════════════════════════════════
# Master data import & company-scoped operations
# ═══════════════════════════════════════════════════════════


def ensure_company(company_id: str, name: str) -> None:
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO companies (company_id, name, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT(company_id) DO NOTHING
        """,
        (company_id, name, datetime.utcnow().isoformat()),
    )
    conn.commit()


def upsert_vendors(rows: list[dict], commit: bool = True) -> None:
    if not rows:
        return
    conn = get_connection()
    for row in rows:
        conn.execute(
            """
            INSERT INTO vendors (
                vendor_id, company_id, name, normalized_name, aliases_json,
                tax_id, supplier_code, status, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(vendor_id) DO UPDATE SET
                company_id=excluded.company_id,
                name=excluded.name,
                normalized_name=excluded.normalized_name,
                aliases_json=excluded.aliases_json,
                tax_id=excluded.tax_id,
                supplier_code=excluded.supplier_code,
                status=excluded.status,
                metadata_json=excluded.metadata_json
            """,
            (
                row["vendor_id"],
                row.get("company_id", "DEFAULT"),
                row["name"],
                row["normalized_name"],
                row.get("aliases_json", "[]"),
                row.get("tax_id"),
                row.get("supplier_code"),
                row.get("status", "active"),
                row.get("metadata_json", "{}"),
            ),
        )
    if commit:
        conn.commit()


def upsert_purchase_orders(rows: list[dict], commit: bool = True) -> None:
    if not rows:
        return
    conn = get_connection()
    for row in rows:
        conn.execute(
            """
            INSERT INTO purchase_orders (
                po_number, company_id, vendor_id, vendor_name, total_amount, currency,
                status, po_type, issue_date, expiry_date, received_amount,
                previously_invoiced, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(company_id, po_number) DO UPDATE SET
                company_id=excluded.company_id,
                vendor_id=excluded.vendor_id,
                vendor_name=excluded.vendor_name,
                total_amount=excluded.total_amount,
                currency=excluded.currency,
                status=excluded.status,
                po_type=excluded.po_type,
                issue_date=excluded.issue_date,
                expiry_date=excluded.expiry_date,
                received_amount=excluded.received_amount,
                previously_invoiced=excluded.previously_invoiced,
                metadata_json=excluded.metadata_json
            """,
            (
                row["po_number"],
                row.get("company_id", "DEFAULT"),
                row["vendor_id"],
                row["vendor_name"],
                row["total_amount"],
                row.get("currency", "USD"),
                row.get("status", "open"),
                row.get("po_type", "standard"),
                row["issue_date"],
                row.get("expiry_date"),
                row.get("received_amount", 0.0),
                row.get("previously_invoiced", 0.0),
                row.get("metadata_json", "{}"),
            ),
        )
    if commit:
        conn.commit()


def upsert_po_lines(rows: list[dict], commit: bool = True) -> None:
    if not rows:
        return
    conn = get_connection()
    for row in rows:
        conn.execute(
            """
            INSERT INTO po_lines (
                company_id, po_number, line_number, description, sku,
                quantity, unit_price, amount, uom, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(company_id, po_number, line_number) DO UPDATE SET
                company_id=excluded.company_id,
                description=excluded.description,
                sku=excluded.sku,
                quantity=excluded.quantity,
                unit_price=excluded.unit_price,
                amount=excluded.amount,
                uom=excluded.uom,
                metadata_json=excluded.metadata_json
            """,
            (
                row.get("company_id", "DEFAULT"),
                row["po_number"],
                row["line_number"],
                row["description"],
                row.get("sku"),
                row["quantity"],
                row["unit_price"],
                row["amount"],
                row.get("uom", "each"),
                row.get("metadata_json", "{}"),
            ),
        )
    if commit:
        conn.commit()


def upsert_grn_records(rows: list[dict], commit: bool = True) -> None:
    if not rows:
        return
    conn = get_connection()
    for row in rows:
        conn.execute(
            """
            INSERT INTO grn_records (
                grn_id, company_id, po_number, received_date, received_amount,
                status, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(grn_id) DO UPDATE SET
                company_id=excluded.company_id,
                po_number=excluded.po_number,
                received_date=excluded.received_date,
                received_amount=excluded.received_amount,
                status=excluded.status,
                metadata_json=excluded.metadata_json
            """,
            (
                row["grn_id"],
                row.get("company_id", "DEFAULT"),
                row["po_number"],
                row["received_date"],
                row["received_amount"],
                row.get("status", "confirmed"),
                row.get("metadata_json", "{}"),
            ),
        )
    if commit:
        conn.commit()


def upsert_po_references(rows: list[dict], commit: bool = True) -> None:
    if not rows:
        return
    conn = get_connection()
    for row in rows:
        conn.execute(
            """
            INSERT INTO po_references (company_id, po_number, reference_type, reference_value, normalized_value)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(company_id, reference_type, normalized_value) DO UPDATE SET
                po_number=excluded.po_number,
                reference_value=excluded.reference_value
            """,
            (
                row.get("company_id", "DEFAULT"),
                row["po_number"],
                row["reference_type"],
                row["reference_value"],
                row["normalized_value"],
            ),
        )
    if commit:
        conn.commit()


def search_pos_by_reference(
    reference_type: str,
    reference_value: str,
    company_id: str = "DEFAULT",
) -> list[dict]:
    """Find POs by typed reference (order_ref, contract_ref, etc.)."""
    import re

    normalized = re.sub(r"[\-\s\.\#]", "", reference_value.upper())
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT po_number FROM po_references
        WHERE company_id = ? AND reference_type = ? AND normalized_value = ?
        """,
        (company_id, reference_type, normalized),
    ).fetchall()
    result = []
    for row in rows:
        po = get_po(row["po_number"], company_id=company_id)
        if po:
            po["_retrieval_method"] = "reference"
            po["_retrieval_confidence"] = 0.9
            result.append(po)
    return result


def search_open_pos_by_vendor_identity(
    vendor_id: str | None,
    vendor_name: str | None,
    company_id: str = "DEFAULT",
) -> list[dict]:
    """Find open POs by vendor_id and/or canonical vendor name on PO header."""
    from app.services.vendor_identity import normalize_vendor_name, vendor_names_equivalent

    seen: set[str] = set()
    results: list[dict] = []

    if vendor_id:
        for po in search_pos_by_vendor(vendor_id, "open", company_id):
            if po["po_number"] not in seen:
                po = _parse_po_metadata(dict(po)) if "metadata" not in po else po
                po["_retrieval_method"] = _retrieval_method_for_po(po, "vendor_search")
                po["_retrieval_confidence"] = 0.75
                results.append(po)
                seen.add(po["po_number"])

    if vendor_name:
        target_norm = normalize_vendor_name(vendor_name)
        for po in get_all_open_pos(company_id):
            if po["po_number"] in seen:
                continue
            if vendor_names_equivalent(vendor_name, po.get("vendor_name", "")):
                po = dict(po)
                po["_retrieval_method"] = _retrieval_method_for_po(po, "vendor_name")
                po["_retrieval_confidence"] = 0.7
                results.append(po)
                seen.add(po["po_number"])
            else:
                vendor = get_vendor_by_id(po.get("vendor_id", ""))
                if vendor and vendor.get("normalized_name") == target_norm:
                    po = dict(po)
                    po["_retrieval_method"] = _retrieval_method_for_po(po, "vendor_name")
                    po["_retrieval_confidence"] = 0.65
                    results.append(po)
                    seen.add(po["po_number"])

    return results


def create_master_data_import(
    import_id: str,
    company_id: str,
    filename: str,
    status: str,
) -> None:
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO master_data_imports (import_id, company_id, filename, status, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (import_id, company_id, filename, status, datetime.utcnow().isoformat()),
    )
    conn.commit()


def complete_master_data_import(
    import_id: str,
    status: str,
    summary: dict,
    errors: list[str],
    batch_id: str | None = None,
    file_checksum: str | None = None,
    classification_summary: dict | None = None,
) -> None:
    conn = get_connection()
    conn.execute(
        """
        UPDATE master_data_imports SET
            status = ?,
            summary_json = ?,
            errors_json = ?,
            completed_at = ?,
            batch_id = COALESCE(?, batch_id),
            file_checksum = COALESCE(?, file_checksum),
            classification_summary_json = COALESCE(?, classification_summary_json)
        WHERE import_id = ?
        """,
        (
            status,
            json.dumps(summary),
            json.dumps(errors),
            datetime.utcnow().isoformat(),
            batch_id,
            file_checksum,
            json.dumps(classification_summary or {}),
            import_id,
        ),
    )
    conn.commit()


def list_master_data_imports(company_id: str = "DEFAULT", limit: int = 20) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT * FROM master_data_imports WHERE company_id = ?
        ORDER BY created_at DESC LIMIT ?
        """,
        (company_id, limit),
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        for field in ("summary_json", "errors_json", "classification_summary_json"):
            if d.get(field):
                try:
                    key = field.replace("_json", "")
                    d[key] = json.loads(d[field])
                except json.JSONDecodeError:
                    pass
        result.append(d)
    return result


def upsert_source_records(rows: list[dict], commit: bool = True) -> None:
    if not rows:
        return
    conn = get_connection()
    for row in rows:
        conn.execute(
            """
            INSERT INTO source_records (
                source_record_id, company_id, record_type, vendor_id, vendor_name,
                invoice_number, invoice_date, invoice_total, invoice_subtotal,
                currency, po_reference, po_reference_status, status,
                import_batch_id, source_row_index, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(company_id, invoice_number, vendor_name) DO UPDATE SET
                record_type=excluded.record_type,
                vendor_id=excluded.vendor_id,
                vendor_name=excluded.vendor_name,
                invoice_date=excluded.invoice_date,
                invoice_total=excluded.invoice_total,
                invoice_subtotal=excluded.invoice_subtotal,
                currency=excluded.currency,
                po_reference=excluded.po_reference,
                po_reference_status=excluded.po_reference_status,
                status=excluded.status,
                import_batch_id=excluded.import_batch_id,
                source_row_index=excluded.source_row_index,
                metadata_json=excluded.metadata_json
            """,
            (
                row["source_record_id"],
                row.get("company_id", "DEFAULT"),
                row["record_type"],
                row.get("vendor_id"),
                row.get("vendor_name"),
                row.get("invoice_number"),
                row.get("invoice_date"),
                row.get("invoice_total"),
                row.get("invoice_subtotal"),
                row.get("currency", "USD"),
                row.get("po_reference"),
                row.get("po_reference_status", "unresolved"),
                row.get("status", "active"),
                row.get("import_batch_id"),
                row.get("source_row_index"),
                row.get("metadata_json", "{}"),
                row.get("created_at", datetime.utcnow().isoformat()),
            ),
        )
    if commit:
        conn.commit()


def get_source_records_by_company(
    company_id: str = "DEFAULT",
    limit: int = 100,
    po_reference_status: str | None = None,
) -> list[dict]:
    conn = get_connection()
    if po_reference_status:
        rows = conn.execute(
            """
            SELECT * FROM source_records WHERE company_id = ? AND po_reference_status = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (company_id, po_reference_status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM source_records WHERE company_id = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (company_id, limit),
        ).fetchall()
    return [_parse_source_record(dict(r)) for r in rows]


def get_source_record(source_record_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM source_records WHERE source_record_id = ?",
        (source_record_id,),
    ).fetchone()
    if not row:
        return None
    return _parse_source_record(dict(row))


def search_source_records_by_vendor(
    vendor_name: str,
    company_id: str = "DEFAULT",
) -> list[dict]:
    conn = get_connection()
    from app.services.vendor_identity import normalize_vendor_name

    norm = normalize_vendor_name(vendor_name)
    rows = conn.execute(
        """
        SELECT * FROM source_records WHERE company_id = ?
        ORDER BY created_at DESC
        """,
        (company_id,),
    ).fetchall()
    results = []
    for row in rows:
        d = _parse_source_record(dict(row))
        vnorm = normalize_vendor_name(d.get("vendor_name") or "")
        if vnorm == norm or norm in vnorm or vnorm in norm:
            results.append(d)
    return results


def search_source_records_by_invoice_number(
    invoice_number: str,
    vendor_name: str | None = None,
    company_id: str = "DEFAULT",
) -> list[dict]:
    from app.services.vendor_identity import normalize_vendor_name

    conn = get_connection()
    if vendor_name:
        norm = normalize_vendor_name(vendor_name)
        rows = conn.execute(
            """
            SELECT * FROM source_records
            WHERE company_id = ? AND invoice_number = ?
            """,
            (company_id, invoice_number),
        ).fetchall()
        results = []
        for row in rows:
            d = _parse_source_record(dict(row))
            vnorm = normalize_vendor_name(d.get("vendor_name") or "")
            if vnorm == norm or norm in vnorm or vnorm in norm:
                results.append(d)
        return results
    rows = conn.execute(
        """
        SELECT * FROM source_records
        WHERE company_id = ? AND invoice_number = ?
        """,
        (company_id, invoice_number),
    ).fetchall()
    return [_parse_source_record(dict(r)) for r in rows]


def _parse_source_record(d: dict) -> dict:
    if d.get("metadata_json"):
        try:
            d["metadata"] = json.loads(d["metadata_json"])
        except json.JSONDecodeError:
            d["metadata"] = {}
    return d


def update_staging_batch_validation(batch_id: str, validation: dict) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE import_staging_batches SET validation_json = ? WHERE batch_id = ?",
        (json.dumps(validation), batch_id),
    )
    conn.commit()


def record_invoice_allocation(
    document_id: str,
    po_number: str,
    invoice_amount: float,
    line_allocations: list[dict] | None = None,
    company_id: str = "DEFAULT",
) -> bool:
    """Idempotent balance consumption after approval."""
    idempotency_key = f"{document_id}:{po_number}"
    conn = get_connection()
    existing = conn.execute(
        "SELECT allocation_id FROM invoice_allocations WHERE idempotency_key = ?",
        (idempotency_key,),
    ).fetchone()
    if existing:
        logger.info("Allocation already posted: %s", idempotency_key)
        return False

    allocation_id = f"ALLOC-{document_id[:8]}-{po_number}"
    conn.execute(
        """
        INSERT INTO invoice_allocations (
            allocation_id, company_id, document_id, po_number,
            invoice_amount, line_allocations_json, posted_at, idempotency_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            allocation_id,
            company_id,
            document_id,
            po_number,
            invoice_amount,
            json.dumps(line_allocations or []),
            datetime.utcnow().isoformat(),
            idempotency_key,
        ),
    )
    po = get_po(po_number, company_id=company_id)
    if po:
        prior = po.get("previously_invoiced", 0)
        update_po_previously_invoiced(po_number, prior + invoice_amount)
        for la in line_allocations or []:
            line_no = la.get("line_number") or la.get("po_line_number")
            qty = la.get("quantity") or la.get("allocated_quantity")
            if line_no is not None and qty is not None:
                update_po_line_invoiced_quantity(
                    po_number, int(line_no), float(qty), company_id=company_id
                )
    conn.commit()
    return True


def update_po_line_invoiced_quantity(
    po_number: str,
    line_number: int,
    quantity: float,
    company_id: str = "DEFAULT",
) -> None:
    conn = get_connection()
    conn.execute(
        """
        UPDATE po_lines SET invoiced_quantity = invoiced_quantity + ?
        WHERE po_number = ? AND line_number = ? AND company_id = ?
        """,
        (quantity, po_number, line_number, company_id),
    )
    conn.commit()


def get_allocation_for_document(document_id: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM invoice_allocations WHERE document_id = ?",
        (document_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════
# Adaptive import staging & mapping profiles
# ═══════════════════════════════════════════════════════════


def create_staging_batch(
    batch_id: str,
    company_id: str,
    filename: str,
    file_checksum: str,
    source_fingerprint: str,
    mapping_json: dict,
    summary_json: dict,
) -> None:
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO import_staging_batches (
            batch_id, company_id, filename, file_checksum, source_fingerprint,
            status, mapping_json, summary_json, created_at
        ) VALUES (?, ?, ?, ?, ?, 'staged', ?, ?, ?)
        """,
        (
            batch_id,
            company_id,
            filename,
            file_checksum,
            source_fingerprint,
            json.dumps(mapping_json),
            json.dumps(summary_json),
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()


def ensure_staging_batch(
    batch_id: str,
    company_id: str,
    filename: str,
    file_checksum: str,
    source_fingerprint: str,
    mapping_json: dict,
    summary_json: dict,
) -> str:
    """Create staging batch or reset existing one for the same file checksum."""
    conn = get_connection()
    existing = conn.execute(
        """
        SELECT batch_id FROM import_staging_batches
        WHERE company_id = ? AND file_checksum = ?
        """,
        (company_id, file_checksum),
    ).fetchone()
    now = datetime.utcnow().isoformat()
    payload = (
        filename,
        source_fingerprint,
        json.dumps(mapping_json),
        json.dumps(summary_json),
        now,
    )
    if existing:
        batch_id = existing["batch_id"]
        conn.execute(
            """
            UPDATE import_staging_batches SET
                filename = ?,
                source_fingerprint = ?,
                status = 'staged',
                mapping_json = ?,
                summary_json = ?,
                validation_json = '{}',
                activated_at = NULL,
                created_at = ?
            WHERE batch_id = ?
            """,
            (*payload, batch_id),
        )
        conn.execute("DELETE FROM import_staging_rows WHERE batch_id = ?", (batch_id,))
    else:
        conn.execute(
            """
            INSERT INTO import_staging_batches (
                batch_id, company_id, filename, file_checksum, source_fingerprint,
                status, mapping_json, summary_json, created_at
            ) VALUES (?, ?, ?, ?, ?, 'staged', ?, ?, ?)
            """,
            (
                batch_id,
                company_id,
                filename,
                file_checksum,
                source_fingerprint,
                json.dumps(mapping_json),
                json.dumps(summary_json),
                now,
            ),
        )
    conn.commit()
    return batch_id


def insert_staging_rows(batch_id: str, rows: list[dict]) -> None:
    if not rows:
        return
    conn = get_connection()
    for row in rows:
        conn.execute(
            """
            INSERT INTO import_staging_rows (
                batch_id, entity, sheet_name, row_index,
                raw_json, canonical_json, metadata_json, classification_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                row["entity"],
                row["sheet_name"],
                row["row_index"],
                json.dumps(row.get("raw_json", {})),
                json.dumps(row.get("canonical_json", {})),
                json.dumps(row.get("metadata_json", {})),
                json.dumps(row.get("classification_json", {})),
            ),
        )
    conn.commit()


def get_staging_batch(batch_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM import_staging_batches WHERE batch_id = ?",
        (batch_id,),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    for field in ("mapping_json", "summary_json", "validation_json", "profile_json"):
        if d.get(field):
            try:
                d[field.replace("_json", "")] = json.loads(d[field])
            except json.JSONDecodeError:
                pass
    return d


def get_staging_batch_by_checksum(company_id: str, file_checksum: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        """
        SELECT * FROM import_staging_batches
        WHERE company_id = ? AND file_checksum = ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (company_id, file_checksum),
    ).fetchone()
    if not row:
        return None
    return dict(row)


def get_staging_rows(batch_id: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM import_staging_rows WHERE batch_id = ? ORDER BY row_index",
        (batch_id,),
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        for field in ("raw_json", "canonical_json", "metadata_json", "classification_json"):
            if d.get(field):
                try:
                    d[field] = json.loads(d[field])
                except json.JSONDecodeError:
                    d[field] = {}
        classification = d.get("classification_json") or {}
        if isinstance(classification, dict):
            d["record_type"] = classification.get("record_type", d.get("entity"))
        result.append(d)
    return result


def mark_staging_batch_activated(batch_id: str) -> None:
    conn = get_connection()
    conn.execute(
        """
        UPDATE import_staging_batches SET status = 'activated', activated_at = ?
        WHERE batch_id = ?
        """,
        (datetime.utcnow().isoformat(), batch_id),
    )


def get_mapping_profile(company_id: str, source_fingerprint: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        """
        SELECT profile_json FROM mapping_profiles
        WHERE company_id = ? AND source_fingerprint = ?
        """,
        (company_id, source_fingerprint),
    ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["profile_json"])
    except (json.JSONDecodeError, TypeError, KeyError):
        return None


def save_mapping_profile(
    company_id: str,
    source_fingerprint: str,
    profile_json: str,
    confirmed_by: str = "system",
) -> None:
    import uuid

    profile_id = f"MP-{uuid.uuid4().hex[:10]}"
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO mapping_profiles (
            profile_id, company_id, source_fingerprint, profile_json, confirmed_by, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(company_id, source_fingerprint) DO UPDATE SET
            profile_json = excluded.profile_json,
            confirmed_by = excluded.confirmed_by,
            updated_at = excluded.updated_at
        """,
        (
            profile_id,
            company_id,
            source_fingerprint,
            profile_json,
            confirmed_by,
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()
