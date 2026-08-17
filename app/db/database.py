"""
InvoiceFlow AI — SQLite Database

Initializes and manages the SQLite database for audit trail storage.
All processing artifacts are stored for full reproducibility.
"""

import logging
import sqlite3
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

_connection = None
_is_postgres = False


class _PgResult:
    def __init__(self, cursor):
        self._cursor = cursor

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        if isinstance(row, dict):
            return row
        cols = [d[0] for d in self._cursor.description]
        return dict(zip(cols, row))

    def fetchall(self):
        rows = self._cursor.fetchall()
        if not rows:
            return []
        if isinstance(rows[0], dict):
            return rows
        cols = [d[0] for d in self._cursor.description]
        return [dict(zip(cols, r)) for r in rows]


class _PgConnection:
    """Postgres connection wrapper with sqlite-style ? placeholders."""

    def __init__(self, conn):
        self._conn = conn

    @property
    def closed(self) -> bool:
        return bool(getattr(self._conn, "closed", 1))

    def execute(self, sql: str, params=()):
        import psycopg2.extras

        sql = sql.replace("?", "%s")
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute(sql, params)
            return _PgResult(cur)
        except Exception:
            self._conn.rollback()
            raise

    def executemany(self, sql: str, params_seq):
        import psycopg2.extras

        sql = sql.replace("?", "%s")
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.executemany(sql, params_seq)
            return _PgResult(cur)
        except Exception:
            self._conn.rollback()
            raise

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def scalar_row(row) -> int | float | str | None:
    """First column from sqlite Row or Postgres dict row."""
    if row is None:
        return None
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


def get_connection():
    """Get database connection — Neon Postgres when DATABASE_URL set, else SQLite."""
    global _connection, _is_postgres
    if _connection is not None:
        if _is_postgres and getattr(_connection, "closed", True):
            _connection = None
        else:
            return _connection

    if settings.database_url:
        import psycopg2

        _connection = _PgConnection(psycopg2.connect(settings.database_url))
        _is_postgres = True
        logger.info("Database connected: Postgres (Neon)")
    else:
        db_path = settings.db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        _connection = conn
        _is_postgres = False
        logger.info(f"Database connected: SQLite {db_path}")
    return _connection

SCHEMA = """
CREATE TABLE IF NOT EXISTS invoice_runs (
    document_id         TEXT PRIMARY KEY,
    filename            TEXT NOT NULL,
    status              TEXT NOT NULL,
    upload_timestamp    TEXT NOT NULL,
    processing_time_seconds REAL DEFAULT 0.0,
    pages_json          TEXT,
    extraction_json     TEXT,
    verification_json   TEXT,
    arithmetic_json     TEXT,
    decision            TEXT,
    decision_explanation_json TEXT,
    retry_count         INTEGER DEFAULT 0,
    error_details       TEXT,
    original_file_path  TEXT,
    stage2_result_json  TEXT,
    stage2_status       TEXT DEFAULT '',
    stage3_result_json  TEXT,
    stage3_status       TEXT DEFAULT '',
    stage4_result_json  TEXT,
    stage4_status       TEXT DEFAULT '',
    stage4_decision     TEXT DEFAULT '',
    stage5_result_json  TEXT,
    stage5_status       TEXT DEFAULT '',
    stage5_explanation_id TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_status ON invoice_runs(status);
CREATE INDEX IF NOT EXISTS idx_upload ON invoice_runs(upload_timestamp);

-- Stage 2: Vendor Master
CREATE TABLE IF NOT EXISTS companies (
    company_id      TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vendors (
    vendor_id       TEXT PRIMARY KEY,
    company_id      TEXT NOT NULL DEFAULT 'DEFAULT',
    name            TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    aliases_json    TEXT DEFAULT '[]',
    tax_id          TEXT,
    supplier_code   TEXT,
    status          TEXT NOT NULL DEFAULT 'active'
);

CREATE INDEX IF NOT EXISTS idx_vendor_normalized ON vendors(normalized_name);
CREATE INDEX IF NOT EXISTS idx_vendor_tax_id ON vendors(tax_id);
CREATE INDEX IF NOT EXISTS idx_vendor_company ON vendors(company_id);

-- Stage 2: Purchase Orders
CREATE TABLE IF NOT EXISTS purchase_orders (
    po_number       TEXT NOT NULL,
    company_id      TEXT NOT NULL DEFAULT 'DEFAULT',
    vendor_id       TEXT NOT NULL,
    vendor_name     TEXT NOT NULL,
    total_amount    REAL NOT NULL,
    currency        TEXT DEFAULT 'USD',
    status          TEXT NOT NULL DEFAULT 'open',
    po_type         TEXT NOT NULL DEFAULT 'standard',
    issue_date      TEXT NOT NULL,
    expiry_date     TEXT,
    received_amount     REAL DEFAULT 0.0,
    previously_invoiced REAL DEFAULT 0.0,
    metadata_json   TEXT DEFAULT '{}',
    PRIMARY KEY (company_id, po_number)
);

CREATE INDEX IF NOT EXISTS idx_po_vendor ON purchase_orders(vendor_id);
CREATE INDEX IF NOT EXISTS idx_po_status ON purchase_orders(status);
CREATE INDEX IF NOT EXISTS idx_po_number ON purchase_orders(po_number);

-- Stage 2: PO Line Items
CREATE TABLE IF NOT EXISTS po_lines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id      TEXT NOT NULL DEFAULT 'DEFAULT',
    po_number       TEXT NOT NULL,
    line_number     INTEGER NOT NULL,
    description     TEXT NOT NULL,
    sku             TEXT,
    quantity        REAL NOT NULL,
    unit_price      REAL NOT NULL,
    amount          REAL NOT NULL,
    uom             TEXT DEFAULT 'each',
    invoiced_quantity REAL DEFAULT 0.0,
    metadata_json   TEXT DEFAULT '{}',
    UNIQUE(company_id, po_number, line_number)
);

-- Typed PO references (order #, contract #, customer ref, etc.)
CREATE TABLE IF NOT EXISTS po_references (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id      TEXT NOT NULL DEFAULT 'DEFAULT',
    po_number       TEXT NOT NULL,
    reference_type  TEXT NOT NULL,
    reference_value TEXT NOT NULL,
    normalized_value TEXT NOT NULL,
    FOREIGN KEY (po_number) REFERENCES purchase_orders(po_number),
    UNIQUE(company_id, reference_type, normalized_value)
);

CREATE INDEX IF NOT EXISTS idx_po_ref_lookup ON po_references(company_id, reference_type, normalized_value);

-- Stage 2: Goods Receipt Notes
CREATE TABLE IF NOT EXISTS grn_records (
    grn_id          TEXT PRIMARY KEY,
    company_id      TEXT NOT NULL DEFAULT 'DEFAULT',
    po_number       TEXT NOT NULL,
    received_date   TEXT NOT NULL,
    received_amount REAL NOT NULL,
    status          TEXT DEFAULT 'confirmed',
    FOREIGN KEY (po_number) REFERENCES purchase_orders(po_number)
);

-- Invoice-to-PO allocations (posted after approval)
CREATE TABLE IF NOT EXISTS invoice_allocations (
    allocation_id   TEXT PRIMARY KEY,
    company_id      TEXT NOT NULL DEFAULT 'DEFAULT',
    document_id     TEXT NOT NULL,
    po_number       TEXT NOT NULL,
    invoice_amount  REAL NOT NULL,
    line_allocations_json TEXT DEFAULT '[]',
    posted_at       TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    FOREIGN KEY (document_id) REFERENCES invoice_runs(document_id)
);

CREATE INDEX IF NOT EXISTS idx_alloc_document ON invoice_allocations(document_id);

-- Master data import audit
CREATE TABLE IF NOT EXISTS master_data_imports (
    import_id       TEXT PRIMARY KEY,
    company_id      TEXT NOT NULL DEFAULT 'DEFAULT',
    filename        TEXT NOT NULL,
    status          TEXT NOT NULL,
    summary_json    TEXT DEFAULT '{}',
    errors_json     TEXT DEFAULT '[]',
    created_at      TEXT NOT NULL,
    completed_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_import_company ON master_data_imports(company_id);

-- Adaptive import staging (lossless raw capture before activation)
CREATE TABLE IF NOT EXISTS import_staging_batches (
    batch_id            TEXT PRIMARY KEY,
    company_id          TEXT NOT NULL DEFAULT 'DEFAULT',
    filename            TEXT NOT NULL,
    file_checksum       TEXT NOT NULL,
    source_fingerprint  TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'staged',
    profile_json        TEXT DEFAULT '{}',
    mapping_json        TEXT DEFAULT '{}',
    validation_json     TEXT DEFAULT '{}',
    summary_json        TEXT DEFAULT '{}',
    created_at          TEXT NOT NULL,
    activated_at        TEXT,
    UNIQUE(company_id, file_checksum)
);

CREATE INDEX IF NOT EXISTS idx_staging_company ON import_staging_batches(company_id);
CREATE INDEX IF NOT EXISTS idx_staging_fingerprint ON import_staging_batches(company_id, source_fingerprint);

CREATE TABLE IF NOT EXISTS import_staging_rows (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id            TEXT NOT NULL,
    entity              TEXT NOT NULL,
    sheet_name          TEXT NOT NULL,
    row_index           INTEGER NOT NULL,
    raw_json            TEXT NOT NULL,
    canonical_json      TEXT DEFAULT '{}',
    metadata_json       TEXT DEFAULT '{}',
    classification_json TEXT DEFAULT '{}',
    FOREIGN KEY (batch_id) REFERENCES import_staging_batches(batch_id)
);

CREATE INDEX IF NOT EXISTS idx_staging_rows_batch ON import_staging_rows(batch_id);

-- Imported invoice/transaction canonical records (PO relationship optional)
CREATE TABLE IF NOT EXISTS source_records (
    source_record_id      TEXT PRIMARY KEY,
    company_id            TEXT NOT NULL DEFAULT 'DEFAULT',
    record_type           TEXT NOT NULL,
    vendor_id             TEXT,
    vendor_name           TEXT,
    invoice_number        TEXT,
    invoice_date          TEXT,
    invoice_total         REAL,
    invoice_subtotal      REAL,
    currency              TEXT DEFAULT 'USD',
    po_reference          TEXT,
    po_reference_status   TEXT DEFAULT 'unresolved',
    status                TEXT DEFAULT 'active',
    import_batch_id       TEXT,
    source_row_index      INTEGER,
    metadata_json         TEXT DEFAULT '{}',
    created_at            TEXT NOT NULL,
    UNIQUE(company_id, invoice_number, vendor_name)
);

CREATE INDEX IF NOT EXISTS idx_source_records_company ON source_records(company_id);
CREATE INDEX IF NOT EXISTS idx_source_records_po_ref ON source_records(company_id, po_reference);
CREATE INDEX IF NOT EXISTS idx_source_records_invoice ON source_records(company_id, invoice_number);

-- Reusable column mapping profiles per company + source fingerprint
CREATE TABLE IF NOT EXISTS mapping_profiles (
    profile_id          TEXT PRIMARY KEY,
    company_id          TEXT NOT NULL DEFAULT 'DEFAULT',
    source_fingerprint  TEXT NOT NULL,
    profile_json        TEXT NOT NULL,
    confirmed_by        TEXT DEFAULT 'system',
    updated_at          TEXT NOT NULL,
    UNIQUE(company_id, source_fingerprint)
);

-- Stage 2: Match Results (audit trail)
CREATE TABLE IF NOT EXISTS po_match_results (
    document_id     TEXT PRIMARY KEY,
    match_status    TEXT NOT NULL,
    match_package_json TEXT NOT NULL,
    matched_at      TEXT NOT NULL,
    FOREIGN KEY (document_id) REFERENCES invoice_runs(document_id)
);

-- Stage 3: Validation Runs (immutable audit trail)
CREATE TABLE IF NOT EXISTS validation_runs (
    validation_run_id   TEXT PRIMARY KEY,
    document_id         TEXT NOT NULL,
    processing_state    TEXT NOT NULL DEFAULT 'COMPLETED',
    overall_state       TEXT NOT NULL,
    reason_codes_json   TEXT DEFAULT '[]',
    checks_json         TEXT,
    controls_json       TEXT DEFAULT '[]',
    evidence_json       TEXT DEFAULT '[]',
    fraud_signals_json  TEXT DEFAULT '[]',
    policy_version      TEXT DEFAULT 'AP-2026.08.1',
    source_snapshots_json TEXT,
    started_at          TEXT NOT NULL,
    completed_at        TEXT,
    parent_run_id       TEXT,
    trigger             TEXT DEFAULT 'initial',
    report_json         TEXT,
    FOREIGN KEY (document_id) REFERENCES invoice_runs(document_id)
);

CREATE INDEX IF NOT EXISTS idx_vr_document ON validation_runs(document_id);
CREATE INDEX IF NOT EXISTS idx_vr_state ON validation_runs(overall_state);

-- Stage 4: Decision Records (immutable audit trail)
CREATE TABLE IF NOT EXISTS decision_records (
    decision_id         TEXT PRIMARY KEY,
    document_id         TEXT NOT NULL,
    validation_run_id   TEXT NOT NULL,
    decision            TEXT NOT NULL,
    decision_substate   TEXT NOT NULL,
    reason_codes_json   TEXT DEFAULT '[]',
    rules_json          TEXT,
    policy_json         TEXT,
    authority_json      TEXT,
    routing_json        TEXT,
    trace_json          TEXT,
    evidence_refs_json  TEXT DEFAULT '[]',
    evidence_summary_json TEXT DEFAULT '[]',
    decided_at          TEXT NOT NULL,
    engine_version      TEXT DEFAULT 'stage4-v2.0',
    processing_time_seconds REAL DEFAULT 0.0,
    record_json         TEXT,
    FOREIGN KEY (document_id) REFERENCES invoice_runs(document_id),
    FOREIGN KEY (validation_run_id) REFERENCES validation_runs(validation_run_id)
);

CREATE INDEX IF NOT EXISTS idx_dec_document ON decision_records(document_id);
CREATE INDEX IF NOT EXISTS idx_dec_decision ON decision_records(decision);

-- Stage 5: Explanation Snapshots (append-only, versioned)
CREATE TABLE IF NOT EXISTS explanation_snapshots (
    explanation_id          TEXT PRIMARY KEY,
    tenant_id               TEXT NOT NULL DEFAULT 'TENANT-DEFAULT',
    decision_id             TEXT NOT NULL,
    invoice_id              TEXT NOT NULL,
    explanation_schema_version TEXT DEFAULT '3.0',
    explanation_status      TEXT NOT NULL,
    narrative_json          TEXT,
    rule_trace_json         TEXT,
    routing_json            TEXT,
    authority_json          TEXT,
    control_verification_json TEXT,
    evidence_refs_json      TEXT DEFAULT '[]',
    evidence_summary_json   TEXT DEFAULT '[]',
    gaps_json               TEXT DEFAULT '[]',
    human_actions_json      TEXT DEFAULT '[]',
    upstream_artifacts_json TEXT DEFAULT '[]',
    policy_version          TEXT,
    policy_hash             TEXT,
    decision_outcome        TEXT,
    decision_substate       TEXT,
    integrity_json          TEXT,
    sampling_json           TEXT,
    snapshot_json           TEXT,
    generated_at            TEXT NOT NULL,
    engine_version          TEXT DEFAULT 'stage5-v3.0',
    processing_time_seconds REAL DEFAULT 0.0,
    UNIQUE(tenant_id, decision_id, explanation_schema_version)
);

CREATE INDEX IF NOT EXISTS idx_exp_decision ON explanation_snapshots(decision_id);
CREATE INDEX IF NOT EXISTS idx_exp_invoice ON explanation_snapshots(invoice_id);
CREATE INDEX IF NOT EXISTS idx_exp_status ON explanation_snapshots(explanation_status);

-- Stage 5: Audit Ledger (append-only, hash-chained)
CREATE TABLE IF NOT EXISTS audit_ledger (
    ledger_sequence     INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id           TEXT NOT NULL DEFAULT 'TENANT-DEFAULT',
    event_type          TEXT NOT NULL,
    aggregate_id        TEXT NOT NULL,
    explanation_id      TEXT,
    decision_id         TEXT,
    invoice_id          TEXT,
    content_hash        TEXT NOT NULL,
    previous_hash       TEXT NOT NULL DEFAULT 'GENESIS',
    event_data_json     TEXT,
    actor_id            TEXT DEFAULT 'system',
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_al_aggregate ON audit_ledger(aggregate_id);
CREATE INDEX IF NOT EXISTS idx_al_type ON audit_ledger(event_type);

-- Enterprise: PO confirmations (Phase 2)
CREATE TABLE IF NOT EXISTS po_confirmations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id         TEXT NOT NULL,
    suggested_snapshot_json TEXT,
    chosen_po_number    TEXT,
    confirmed_by        TEXT NOT NULL,
    notes               TEXT DEFAULT '',
    action              TEXT NOT NULL DEFAULT 'confirm',
    confirmed_at        TEXT NOT NULL,
    FOREIGN KEY (document_id) REFERENCES invoice_runs(document_id)
);

CREATE INDEX IF NOT EXISTS idx_po_conf_document ON po_confirmations(document_id);

-- Enterprise: Review work items (Phase 3)
CREATE TABLE IF NOT EXISTS review_work_items (
    work_item_id        TEXT PRIMARY KEY,
    document_id         TEXT NOT NULL,
    queue               TEXT NOT NULL,
    reason_codes_json   TEXT DEFAULT '[]',
    priority            TEXT DEFAULT 'NORMAL',
    sla_due_at          TEXT,
    status              TEXT NOT NULL DEFAULT 'open',
    assigned_to         TEXT DEFAULT '',
    stage1_status       TEXT DEFAULT '',
    stage2_status       TEXT DEFAULT '',
    stage4_decision     TEXT DEFAULT '',
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    FOREIGN KEY (document_id) REFERENCES invoice_runs(document_id)
);

CREATE INDEX IF NOT EXISTS idx_rwi_queue ON review_work_items(queue);
CREATE INDEX IF NOT EXISTS idx_rwi_status ON review_work_items(status);
CREATE INDEX IF NOT EXISTS idx_rwi_document ON review_work_items(document_id);

-- Enterprise: Vendor profiles (Phase 4)
CREATE TABLE IF NOT EXISTS vendor_profiles (
    vendor_id           TEXT PRIMARY KEY,
    profile_json        TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

-- Enterprise: Extraction feedback (Phase 4)
CREATE TABLE IF NOT EXISTS extraction_feedback (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id         TEXT NOT NULL,
    vendor_id           TEXT DEFAULT '',
    field_name          TEXT NOT NULL,
    original_value      TEXT,
    corrected_value     TEXT,
    actor_id            TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    FOREIGN KEY (document_id) REFERENCES invoice_runs(document_id)
);

CREATE INDEX IF NOT EXISTS idx_feedback_vendor ON extraction_feedback(vendor_id);

-- Async processing jobs (Inngest / job polling)
CREATE TABLE IF NOT EXISTS processing_jobs (
    job_id              TEXT PRIMARY KEY,
    document_id         TEXT DEFAULT '',
    filename            TEXT NOT NULL,
    blob_url            TEXT DEFAULT '',
    storage_key         TEXT DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'queued',
    stage_status_json   TEXT DEFAULT '{}',
    error_message       TEXT DEFAULT '',
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON processing_jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_document ON processing_jobs(document_id);
"""

MIGRATION_COLUMNS = [
    ("invoice_runs", "reconciliation_json", "TEXT"),
    ("invoice_runs", "document_quality_score", "REAL"),
    ("invoice_runs", "confirmed_po_number", "TEXT DEFAULT ''"),
    ("invoice_runs", "company_id", "TEXT DEFAULT 'DEFAULT'"),
    ("explanation_snapshots", "human_actions_json", "TEXT DEFAULT '[]'"),
    ("vendors", "company_id", "TEXT DEFAULT 'DEFAULT'"),
    ("purchase_orders", "company_id", "TEXT DEFAULT 'DEFAULT'"),
    ("po_lines", "company_id", "TEXT DEFAULT 'DEFAULT'"),
    ("po_lines", "invoiced_quantity", "REAL DEFAULT 0.0"),
    ("grn_records", "company_id", "TEXT DEFAULT 'DEFAULT'"),
    ("vendors", "metadata_json", "TEXT DEFAULT '{}'"),
    ("purchase_orders", "metadata_json", "TEXT DEFAULT '{}'"),
    ("po_lines", "metadata_json", "TEXT DEFAULT '{}'"),
    ("grn_records", "metadata_json", "TEXT DEFAULT '{}'"),
    ("master_data_imports", "batch_id", "TEXT"),
    ("master_data_imports", "file_checksum", "TEXT"),
    ("invoice_runs", "evidence_profile_json", "TEXT"),
    ("invoice_runs", "extraction_quality", "TEXT DEFAULT ''"),
    ("invoice_runs", "workflow_state", "TEXT DEFAULT ''"),
    ("master_data_imports", "classification_summary_json", "TEXT DEFAULT '{}'"),
    ("import_staging_rows", "classification_json", "TEXT DEFAULT '{}'"),
]


def _migrate_columns(conn) -> None:
    """Add new columns to existing tables if missing."""
    from app.db.sql_dialect import now_expr

    for table, column, col_type in MIGRATION_COLUMNS:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            if hasattr(conn, "commit"):
                conn.commit()
            logger.info("Migrated: %s.%s", table, column)
        except Exception:
            if hasattr(conn, "rollback"):
                conn.rollback()

    # Ensure default company exists for company-scoped master data
    try:
        conn.execute(
            f"""
            INSERT INTO companies (company_id, name, created_at)
            VALUES (?, ?, {now_expr()})
            ON CONFLICT(company_id) DO NOTHING
            """,
            ("DEFAULT", "Default Company"),
        )
        if hasattr(conn, "commit"):
            conn.commit()
    except Exception:
        if hasattr(conn, "rollback"):
            conn.rollback()


def _migrate_composite_po_keys(conn) -> None:
    """Rebuild purchase_orders with (company_id, po_number) PK if legacy schema."""
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='purchase_orders'"
        ).fetchone()
        if not row or not row[0]:
            return
        ddl = row[0]
        if "PRIMARY KEY (company_id, po_number)" in ddl:
            return
        logger.info("Migrating purchase_orders to composite primary key")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS purchase_orders_v2 (
                po_number TEXT NOT NULL,
                company_id TEXT NOT NULL DEFAULT 'DEFAULT',
                vendor_id TEXT NOT NULL,
                vendor_name TEXT NOT NULL,
                total_amount REAL NOT NULL,
                currency TEXT DEFAULT 'USD',
                status TEXT NOT NULL DEFAULT 'open',
                po_type TEXT NOT NULL DEFAULT 'standard',
                issue_date TEXT NOT NULL,
                expiry_date TEXT,
                received_amount REAL DEFAULT 0.0,
                previously_invoiced REAL DEFAULT 0.0,
                metadata_json TEXT DEFAULT '{}',
                PRIMARY KEY (company_id, po_number)
            )
            """
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO purchase_orders_v2
            SELECT po_number, company_id, vendor_id, vendor_name, total_amount, currency,
                   status, po_type, issue_date, expiry_date, received_amount,
                   previously_invoiced, COALESCE(metadata_json, '{}')
            FROM purchase_orders
            """
        )
        conn.execute("DROP TABLE purchase_orders")
        conn.execute("ALTER TABLE purchase_orders_v2 RENAME TO purchase_orders")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_po_vendor ON purchase_orders(vendor_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_po_status ON purchase_orders(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_po_number ON purchase_orders(po_number)")
    except Exception as exc:
        logger.debug("Composite PO migration skipped: %s", exc)


def _postgres_schema_sql(schema: str) -> str:
    """Adapt SQLite-oriented DDL for Postgres."""
    schema = schema.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
    schema = schema.replace(
        "FOREIGN KEY (po_number) REFERENCES purchase_orders(po_number)",
        "FOREIGN KEY (company_id, po_number) REFERENCES purchase_orders(company_id, po_number)",
    )
    return schema


def init_db() -> None:
    """Initialize the database schema."""
    global _is_postgres
    conn = get_connection()
    schema = SCHEMA
    if _is_postgres:
        schema = _postgres_schema_sql(schema)
        for stmt in schema.split(";"):
            stmt = stmt.strip()
            if stmt:
                try:
                    conn.execute(stmt)
                    conn.commit()
                except Exception as exc:
                    if hasattr(conn, "rollback"):
                        conn.rollback()
                    logger.warning("Schema stmt skipped: %s — %s", stmt[:60], exc)
    else:
        conn.executescript(schema)
        _migrate_columns(conn)
        _migrate_composite_po_keys(conn)
        conn.commit()
        logger.info("Database schema initialized")
        return
    _migrate_columns(conn)
    conn.commit()
    if _is_postgres and not settings.auto_seed_on_startup:
        from app.db import repository

        repository.purge_demo_catalog_pos()
    logger.info("Database schema initialized")


def close_db() -> None:
    """Close the database connection."""
    global _connection
    if _connection is not None:
        if hasattr(_connection, "close"):
            _connection.close()
        _connection = None
        logger.info("Database connection closed")
