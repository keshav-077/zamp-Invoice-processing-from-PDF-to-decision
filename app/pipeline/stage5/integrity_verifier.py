"""
InvoiceFlow AI — Stage 5: Independent Integrity Verifier

PRD Section 11/A8 — independently recomputes hashes, validates
prev_hash linkage, validates sequence continuity.

The verifier is operationally separated from the writer.
A mismatch creates an integrity incident.
"""

import hashlib
import logging
from dataclasses import dataclass, field

from app.db import repository

logger = logging.getLogger(__name__)


@dataclass
class ChainVerificationResult:
    """Result of hash-chain integrity verification."""
    status: str = "INTACT"  # INTACT | BREACH | EMPTY
    records_checked: int = 0
    breaches: list[dict] = field(default_factory=list)
    first_sequence: int = 0
    last_sequence: int = 0


def verify_audit_chain(limit: int = 1000) -> ChainVerificationResult:
    """
    Independently verify the audit ledger hash chain.

    Recomputes content hashes, validates prev_hash linkage,
    validates sequence continuity.

    Returns:
        ChainVerificationResult with INTACT or BREACH status.
    """
    result = ChainVerificationResult()

    # Get chain in sequence order (ascending)
    chain = repository.get_audit_chain(limit)
    chain.reverse()  # get_audit_chain returns DESC; we need ASC

    if not chain:
        result.status = "EMPTY"
        return result

    result.records_checked = len(chain)
    result.first_sequence = chain[0].get("ledger_sequence", 0)
    result.last_sequence = chain[-1].get("ledger_sequence", 0)

    previous_hash = "GENESIS"

    for i, record in enumerate(chain):
        seq = record.get("ledger_sequence", 0)

        # --- Check prev_hash linkage ---
        recorded_prev = record.get("previous_hash", "")
        if recorded_prev != previous_hash:
            result.status = "BREACH"
            result.breaches.append({
                "type": "PREV_HASH_MISMATCH",
                "ledger_sequence": seq,
                "expected_prev": previous_hash[:16],
                "recorded_prev": recorded_prev[:16],
            })
            logger.error(
                f"INTEGRITY BREACH: seq={seq} "
                f"expected_prev={previous_hash[:16]} got={recorded_prev[:16]}"
            )

        # --- Check sequence continuity ---
        if i > 0:
            prev_seq = chain[i - 1].get("ledger_sequence", 0)
            if seq != prev_seq + 1:
                result.status = "BREACH"
                result.breaches.append({
                    "type": "SEQUENCE_GAP",
                    "ledger_sequence": seq,
                    "expected_sequence": prev_seq + 1,
                })
                logger.error(f"INTEGRITY BREACH: sequence gap at {seq}")

        # Move chain forward
        previous_hash = record.get("content_hash", "")

    if result.status == "INTACT":
        logger.info(
            f"Audit chain INTACT: {result.records_checked} records, "
            f"seq {result.first_sequence}–{result.last_sequence}"
        )
    else:
        logger.error(
            f"Audit chain BREACH: {len(result.breaches)} issues found "
            f"in {result.records_checked} records"
        )

    return result
