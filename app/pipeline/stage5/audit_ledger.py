"""
InvoiceFlow AI — Stage 5: Hash-Chained Audit Ledger

PRD Section 11 — append-only, tamper-evident audit records.

Record N:
    content_hash = SHA256(canonical_record_N)
    previous_hash = content_hash(record N-1)

Chain:
    record_001 → record_002 → record_003 → ...
"""

import hashlib
import json
import logging
from datetime import datetime, timezone

from app.db import repository

logger = logging.getLogger(__name__)


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of canonical content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def append_explanation_audit(
    explanation_id: str,
    decision_id: str,
    invoice_id: str,
    explanation_json: str,
    tenant_id: str = "TENANT-DEFAULT",
    actor_id: str = "system",
) -> int:
    """
    Append an explanation event to the hash-chained audit ledger.

    Returns:
        ledger_sequence number
    """
    # Get previous hash for chain
    previous_hash = repository.get_last_audit_hash()

    # Compute content hash
    content_hash = compute_content_hash(explanation_json)

    # Prepare event data
    event_data = {
        "explanation_id": explanation_id,
        "decision_id": decision_id,
        "invoice_id": invoice_id,
        "content_hash": content_hash,
        "previous_hash": previous_hash,
    }

    sequence = repository.append_audit_event(
        tenant_id=tenant_id,
        event_type="explanation.created",
        aggregate_id=invoice_id,
        content_hash=content_hash,
        previous_hash=previous_hash,
        explanation_id=explanation_id,
        decision_id=decision_id,
        invoice_id=invoice_id,
        event_data_json=json.dumps(event_data),
        actor_id=actor_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    logger.info(
        f"Audit: seq={sequence} explanation={explanation_id} "
        f"hash={content_hash[:12]}... prev={previous_hash[:12]}..."
    )
    return sequence
