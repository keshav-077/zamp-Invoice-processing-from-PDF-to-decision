"""Create and manage review work items from pipeline outcomes."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from app.db import repository
from app.models.pipeline import PipelineResult
from app.models.review import ReviewWorkItem
from app.pipeline.stage4.routing_engine import ROUTING_CONFIG

logger = logging.getLogger(__name__)


def _sla_hours_for_queue(queue: str) -> int:
    for cfg in ROUTING_CONFIG.values():
        if cfg.get("target") == queue:
            return int(cfg.get("sla_hours", 48))
    return 48


def create_work_items_from_pipeline(result: PipelineResult) -> list[ReviewWorkItem]:
    """Create review queue items based on Stage 1–4 signals."""
    items: list[ReviewWorkItem] = []
    now = datetime.now(timezone.utc)
    reason_codes: list[str] = []

    if result.status == "needs_human_review":
        reason_codes.append("STAGE1_REVIEW")
    if result.extraction_quality and result.extraction_quality.value == "extraction_weak":
        reason_codes.append("EXTRACTION_PARTIAL")
    if result.stage2_status == "no_matching_evidence":
        reason_codes.append("NO_MATCHING_EVIDENCE")
    if result.stage2_status in ("ambiguous_match", "multiple_candidates"):
        reason_codes.append("PO_AMBIGUOUS")
    if result.reconciliation and result.reconciliation.overall_status == "residual_review":
        reason_codes.append("UNEXPLAINED_RESIDUAL")
    if result.document_quality_score < 0.5:
        reason_codes.append("POOR_SCAN_QUALITY")
    if result.stage2_status in ("ambiguous_match", "waiting_for_po", "suggested_po_match", "partial_match"):
        reason_codes.append("PO_CONFIRMATION_REQUIRED")
    if result.stage3_status in ("REVIEW_REQUIRED", "HOLD"):
        reason_codes.append("VALIDATION_REVIEW")
    if result.stage4_status and result.stage4_status not in ("AUTO_APPROVED", "TERMINAL_REJECT"):
        reason_codes.append("CONTROL_PENDING")

    if not reason_codes:
        return items

    queue = "ap-exception-queue"
    if "POOR_SCAN_QUALITY" in reason_codes:
        queue = "scan-quality-queue"
    elif result.stage4_status in ("FRAUD_REVIEW",):
        queue = "security-fraud-queue"
    elif result.stage4_decision == "REVIEW_REQUIRED":
        routing = ROUTING_CONFIG.get(result.stage4_status or "", {})
        queue = routing.get("target") or queue

    sla_hours = _sla_hours_for_queue(queue)
    priority = "HIGH" if "POOR_SCAN_QUALITY" in reason_codes else "NORMAL"
    if result.stage4_status in ("FRAUD_REVIEW", "HIGH_PRIORITY_REVIEW"):
        priority = "URGENT"

    item = ReviewWorkItem(
        document_id=result.document_id,
        queue=queue,
        reason_codes=reason_codes,
        priority=priority,
        sla_due_at=(now + timedelta(hours=sla_hours)).isoformat(),
        stage1_status=result.status,
        stage2_status=result.stage2_status,
        stage4_decision=result.stage4_decision or "",
    )
    repository.save_review_work_item(item)
    items.append(item)
    logger.info(f"Created work item {item.work_item_id} for {result.document_id}")
    return items
