"""Human review actions, field correction, and partial pipeline re-runs."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

from app.db import repository
from app.models.explanation import HumanAction
from app.models.extraction import InvoiceExtraction, FieldExtraction
from app.models.review import HumanActionRequest
from app.models.verification import VerificationResult
from app.pipeline.normalizer import normalize_extraction
from app.services.pipeline_rerun_service import (
    _build_confirmed_match_package,
    complete_review_work_items,
    rerun_stages_2_through_5,
)

logger = logging.getLogger(__name__)


def _apply_corrections(extraction: InvoiceExtraction, corrections: dict) -> InvoiceExtraction:
    data = extraction.model_dump()
    for field_name, value in corrections.items():
        if field_name not in data or field_name == "line_items":
            continue
        field = data[field_name]
        if isinstance(field, dict):
            field["value"] = value
            field["status"] = "extracted"
            field["confidence"] = max(float(field.get("confidence", 0)), 0.95)
    return InvoiceExtraction.model_validate(data)


def record_human_action(document_id: str, request: HumanActionRequest) -> HumanAction:
    """Append a human action to the audit trail."""
    action = HumanAction(
        action_type=request.action_type,
        actor_id=request.actor_id,
        detail=request.detail,
        outcome=request.outcome,
    )
    repository.append_human_action(document_id, action)

    content = json.dumps(action.model_dump(), sort_keys=True)
    repository.append_audit_event(
        tenant_id="TENANT-DEFAULT",
        event_type="HUMAN_ACTION",
        aggregate_id=document_id,
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        previous_hash=repository.get_last_audit_hash(),
        invoice_id=document_id,
        event_data_json=content,
        actor_id=request.actor_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    return action


def apply_field_correction_and_rerun(document_id: str, request: HumanActionRequest) -> dict:
    """Apply field corrections and re-run Stages 2–5."""
    run = repository.get_run(document_id)
    if not run:
        raise ValueError("Invoice not found")

    extraction_data = run.get("extraction_json")
    if not extraction_data:
        raise ValueError("No extraction to correct")

    extraction = InvoiceExtraction.model_validate(extraction_data)
    corrections = request.field_corrections or {}
    for field_name, new_value in corrections.items():
        old = getattr(extraction, field_name, None)
        if hasattr(old, "value"):
            repository.save_extraction_feedback(
                document_id=document_id,
                vendor_id=extraction.vendor_name.value or "",
                field_name=field_name,
                original_value=str(old.value) if old.value is not None else None,
                corrected_value=str(new_value),
                actor_id=request.actor_id,
            )

    extraction = _apply_corrections(extraction, corrections)
    extraction = normalize_extraction(extraction)

    verification = run.get("verification_json")
    verification_obj = (
        VerificationResult.model_validate(verification)
        if isinstance(verification, dict)
        else VerificationResult(verification_status="unavailable", overall_confidence=0)
    )

    result = rerun_stages_2_through_5(
        document_id,
        extraction,
        verification=verification_obj,
    )

    record_human_action(document_id, request)
    complete_review_work_items(document_id)

    return {
        "document_id": document_id,
        "status": result.status,
        "stage2_status": result.stage2_status,
        "stage3_status": result.stage3_status,
        "stage4_decision": result.stage4_decision,
        "stage5_status": result.stage5_status,
    }


def reject_po_suggestions(
    document_id: str,
    manual_po_number: str | None,
    rejected_by: str,
    notes: str = "",
) -> dict:
    """Human rejects PO suggestions; records audit and updates match state."""
    run = repository.get_run(document_id)
    if not run:
        raise ValueError("Invoice not found")

    stage2_data = run.get("stage2_result_json") or {}
    snapshot = json.dumps(stage2_data.get("suggested_candidates", []))

    repository.save_po_confirmation(
        document_id=document_id,
        chosen_po_number=manual_po_number,
        confirmed_by=rejected_by,
        notes=notes,
        action="reject",
        suggested_snapshot_json=snapshot,
    )

    stage2_data["match_status"] = "po_suggestions_rejected"
    stage2_data["suggestion_mode"] = False
    stage2_data["matched_pos"] = []
    stage2_data["next_stage"] = "human_review"
    if manual_po_number:
        stage2_data["manual_po_number"] = manual_po_number

    match_json = json.dumps(stage2_data)
    repository.save_match_result(document_id, "po_suggestions_rejected", match_json)
    repository.update_stage2_match(document_id, "po_suggestions_rejected", match_json)

    complete_review_work_items(document_id)

    record_human_action(
        document_id,
        HumanActionRequest(
            action_type="reject_po_suggestions",
            actor_id=rejected_by,
            detail=notes or "PO suggestions rejected",
            outcome="rejected",
        ),
    )

    return {
        "document_id": document_id,
        "status": "po_suggestions_rejected",
        "manual_po": manual_po_number,
        "stage2_status": "po_suggestions_rejected",
    }


def confirm_po_match(document_id: str, po_number: str, confirmed_by: str, notes: str = "") -> dict:
    """Human confirms a PO suggestion; re-runs Stages 2–5 with real line matching."""
    run = repository.get_run(document_id)
    if not run:
        raise ValueError("Invoice not found")

    stage2_data = run.get("stage2_result_json") or {}
    snapshot = json.dumps(stage2_data.get("suggested_candidates", []))

    repository.save_po_confirmation(
        document_id=document_id,
        chosen_po_number=po_number,
        confirmed_by=confirmed_by,
        notes=notes,
        action="confirm",
        suggested_snapshot_json=snapshot,
    )

    extraction = InvoiceExtraction.model_validate(run["extraction_json"])
    extraction.po_reference = FieldExtraction(
        value=po_number, confidence=1.0, status="extracted"
    )

    match_package = _build_confirmed_match_package(
        document_id, extraction, po_number, confirmed_by
    )

    verification = run.get("verification_json")
    verification_obj = (
        VerificationResult.model_validate(verification)
        if isinstance(verification, dict)
        else VerificationResult(verification_status="unavailable", overall_confidence=0)
    )

    result = rerun_stages_2_through_5(
        document_id,
        extraction,
        match_package=match_package,
        force_exact_po=True,
        verification=verification_obj,
    )

    complete_review_work_items(document_id)

    return {
        "document_id": document_id,
        "confirmed_po": po_number,
        "stage2_status": result.stage2_status,
        "stage3_status": result.stage3_status,
        "stage4_decision": result.stage4_decision,
        "stage5_status": result.stage5_status,
    }
