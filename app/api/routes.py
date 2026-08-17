"""
InvoiceFlow AI — API Routes

REST endpoints for invoice upload, processing, history, and stats.
"""

import json
import logging
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException, Query, Request, Depends, Form, BackgroundTasks
from fastapi.responses import FileResponse

from app.config import settings
from app.db import repository
from app.middleware.auth import optional_auth
from app.middleware.rate_limit import rate_limit
from app.pipeline.orchestrator import PipelineOrchestrator
from app.providers.factory import get_provider, get_available_providers
from app.storage.storage_service import get_storage
from app.jobs.job_service import create_job
from app.deploy import evaluate_deploy_readiness
from app.jobs.inngest_handler import schedule_invoice_job
from app.services.upload_files import SUPPORTED_UPLOAD_EXTENSIONS, resolve_upload_extension

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["invoices"])


@router.get("/blob/upload-token")
async def get_blob_upload_token(request: Request, _user: dict | None = Depends(optional_auth)):
    """Return Vercel Blob client upload token (direct browser upload >4.5MB)."""
    await rate_limit(request, bucket="blob-token", limit=20)
    if not settings.blob_read_write_token:
        raise HTTPException(status_code=501, detail="Blob storage not configured")
    return {
        "token": settings.blob_read_write_token,
        "pathname_prefix": "invoices/",
    }


@router.post("/jobs", status_code=202)
async def create_processing_job(
    request: Request,
    body: dict,
    background_tasks: BackgroundTasks,
    _user: dict | None = Depends(optional_auth),
):
    """Enqueue invoice processing after client-side Blob upload."""
    await rate_limit(request, bucket="jobs", limit=10)
    filename = body.get("filename")
    blob_url = body.get("blob_url", "")
    storage_key = body.get("storage_key") or blob_url
    if not filename:
        raise HTTPException(status_code=400, detail="filename required")

    job = create_job(filename=filename, blob_url=blob_url, storage_key=storage_key)
    mode = await schedule_invoice_job(job["job_id"], background_tasks=background_tasks)
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "message": "Processing queued",
        "processing_mode": mode,
    }


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Poll real pipeline progress for async jobs."""
    job = repository.get_processing_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "document_id": job.get("document_id"),
        "stage_status": job.get("stage_status", {}),
        "error_message": job.get("error_message", ""),
        "filename": job.get("filename"),
    }


@router.post("/upload")
async def upload_invoice(request: Request, file: UploadFile = File(...), _user: dict | None = Depends(optional_auth)):
    """
    Upload an invoice file and process it through the Stage 1 pipeline.

    Supported formats: PDF, PNG, JPG, JPEG
    Returns the complete pipeline result with audit trail.
    """
    await rate_limit(request, bucket="upload", limit=10)
    # Validate file extension
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in settings.supported_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. Supported: {', '.join(settings.supported_extensions)}",
        )

    # Save uploaded file
    upload_dir = settings.upload_path
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Use unique name to avoid collisions
    unique_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    file_path = upload_dir / unique_name

    try:
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        logger.info(f"File saved: {file_path} ({len(content)} bytes)")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    # Process through pipeline
    try:
        provider = get_provider()
        orchestrator = PipelineOrchestrator(provider)
        result = await orchestrator.process_invoice(file_path)

        # Save to database
        repository.save_run(result)

        return result.model_dump()

    except Exception as e:
        logger.error(f"Pipeline error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Processing failed: {e}")


@router.post("/upload/async", status_code=202)
async def upload_invoice_async(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    _user: dict | None = Depends(optional_auth),
):
    """Upload file to storage and enqueue async processing job."""
    await rate_limit(request, bucket="upload", limit=10)
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in settings.supported_extensions:
        supported = ", ".join(settings.supported_extensions)
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. Supported: {supported}",
        )

    try:
        content = await file.read()
        unique_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
        storage = get_storage()
        storage_key, blob_url = await storage.save_upload(unique_name, content)

        job = create_job(filename=file.filename, blob_url=blob_url, storage_key=storage_key)
        mode = await schedule_invoice_job(job["job_id"], background_tasks=background_tasks)
        return {
            "job_id": job["job_id"],
            "status": "queued",
            "filename": file.filename,
            "processing_mode": mode,
        }
    except HTTPException:
        raise
    except RuntimeError as exc:
        logger.exception("Async upload storage failed")
        raise HTTPException(
            status_code=503,
            detail=f"File storage unavailable: {exc}. Configure BLOB_READ_WRITE_TOKEN on Vercel.",
        ) from exc
    except Exception as exc:
        logger.exception("Async upload failed")
        from app.db.database import get_connection

        conn = get_connection()
        if hasattr(conn, "rollback"):
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}") from exc


@router.get("/invoices")
async def list_invoices(
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List all processed invoices with optional filtering and pagination."""
    runs = repository.list_runs(
        status_filter=status,
        limit=limit,
        offset=offset,
    )
    return {"invoices": runs, "count": len(runs)}


@router.get("/invoices/{document_id}")
async def get_invoice(document_id: str):
    """Get the full audit trail for a specific invoice."""
    run = repository.get_run(document_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return run


@router.get("/invoices/{document_id}/original")
async def get_original_file(document_id: str):
    """Serve the original uploaded invoice file."""
    run = repository.get_run(document_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    file_path = Path(run.get("original_file_path", ""))
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Original file not found")

    return FileResponse(
        path=str(file_path),
        filename=run.get("filename", "invoice"),
        media_type="application/octet-stream",
    )


@router.get("/stats")
async def get_stats():
    """Get dashboard summary statistics."""
    return repository.get_stats()


@router.get("/health")
async def health_check():
    """Health check with provider availability and deploy readiness."""
    available = get_available_providers()
    deploy = evaluate_deploy_readiness()
    status = "healthy"
    if not available:
        status = "degraded"
    elif settings.is_vercel and not deploy.ready:
        status = "degraded"
    return {
        "status": status,
        "available_providers": available,
        "configured_priority": settings.provider_list,
        "deploy": deploy.to_dict(),
    }


# ═══════════════════════════════════════════════════
# Stage 2 — Vendor & PO Endpoints
# ═══════════════════════════════════════════════════

@router.get("/vendors")
async def list_vendors():
    """List all vendors from the Vendor Master."""
    vendors = repository.get_all_vendors()
    return {"vendors": vendors, "count": len(vendors)}


@router.get("/purchase-orders")
async def list_purchase_orders(
    vendor_id: str | None = Query(None),
    status: str = Query("open"),
):
    """List purchase orders with optional vendor/status filter."""
    if vendor_id:
        pos = repository.search_pos_by_vendor(vendor_id, status)
    else:
        pos = repository.get_all_open_pos()
    return {"purchase_orders": pos, "count": len(pos)}


@router.get("/purchase-orders/{po_number}")
async def get_purchase_order(po_number: str):
    """Get a purchase order with its line items."""
    po = repository.get_po(po_number)
    if po is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    po["grn_records"] = repository.get_grn_for_po(po_number)
    return po


# ═══════════════════════════════════════════════════════════
# STAGE 3 — Validation Endpoints
# ═══════════════════════════════════════════════════════════


@router.get("/validation/{document_id}")
async def get_validation_report(document_id: str):
    """Get the latest validation report for an invoice."""
    history = repository.get_validation_history(document_id)
    if not history:
        raise HTTPException(status_code=404, detail="No validation report found")
    latest = history[0]
    return {
        "validation_run_id": latest.get("validation_run_id"),
        "document_id": document_id,
        "overall_state": latest.get("overall_state"),
        "processing_state": latest.get("processing_state"),
        "reason_codes": latest.get("reason_codes_json", []),
        "checks": latest.get("checks_json"),
        "controls": latest.get("controls_json", []),
        "evidence": latest.get("evidence_json", []),
        "policy_version": latest.get("policy_version"),
        "started_at": latest.get("started_at"),
        "completed_at": latest.get("completed_at"),
    }


@router.get("/validation/{document_id}/history")
async def get_validation_history(document_id: str):
    """Get all validation runs for an invoice (immutable history)."""
    history = repository.get_validation_history(document_id)
    return {"document_id": document_id, "runs": history, "count": len(history)}


@router.get("/validation/{document_id}/checks")
async def get_validation_checks(document_id: str):
    """Get individual check details for the latest validation run."""
    history = repository.get_validation_history(document_id)
    if not history:
        raise HTTPException(status_code=404, detail="No validation report found")
    latest = history[0]
    return {
        "document_id": document_id,
        "validation_run_id": latest.get("validation_run_id"),
        "overall_state": latest.get("overall_state"),
        "checks": latest.get("checks_json"),
    }


# ═══════════════════════════════════════════════════════════
# STAGE 4 — Decision Endpoints
# ═══════════════════════════════════════════════════════════


@router.get("/decision/{document_id}")
async def get_decision(document_id: str):
    """Get the latest decision record for an invoice."""
    history = repository.get_decision_history(document_id)
    if not history:
        raise HTTPException(status_code=404, detail="No decision record found")
    latest = history[0]
    return {
        "decision_id": latest.get("decision_id"),
        "document_id": document_id,
        "decision": latest.get("decision"),
        "decision_substate": latest.get("decision_substate"),
        "reason_codes": latest.get("reason_codes_json", []),
        "policy": latest.get("policy_json"),
        "authority": latest.get("authority_json"),
        "routing": latest.get("routing_json"),
        "decided_at": latest.get("decided_at"),
        "engine_version": latest.get("engine_version"),
    }


@router.get("/decision/{document_id}/history")
async def get_decision_history(document_id: str):
    """Get all decision records for an invoice (immutable history)."""
    history = repository.get_decision_history(document_id)
    return {"document_id": document_id, "decisions": history, "count": len(history)}


@router.get("/decision/{document_id}/trace")
async def get_decision_trace(document_id: str):
    """Get the complete decision trace for the latest decision."""
    history = repository.get_decision_history(document_id)
    if not history:
        raise HTTPException(status_code=404, detail="No decision record found")
    latest = history[0]
    return {
        "decision_id": latest.get("decision_id"),
        "document_id": document_id,
        "decision": latest.get("decision"),
        "trace": latest.get("trace_json"),
        "evidence_refs": latest.get("evidence_refs_json", []),
        "evidence_summary": latest.get("evidence_summary_json", []),
    }


# ═══════════════════════════════════════════════════════════
# STAGE 5 — Explanation & Audit Endpoints
# ═══════════════════════════════════════════════════════════


@router.get("/explanation/{document_id}")
async def get_explanation(document_id: str):
    """Get the latest explanation snapshot for an invoice."""
    exp = repository.get_explanation(document_id)
    if not exp:
        raise HTTPException(status_code=404, detail="No explanation found")
    return {
        "explanation_id": exp.get("explanation_id"),
        "document_id": document_id,
        "decision_id": exp.get("decision_id"),
        "explanation_status": exp.get("explanation_status"),
        "decision_outcome": exp.get("decision_outcome"),
        "decision_substate": exp.get("decision_substate"),
        "narrative": exp.get("narrative_json"),
        "policy_version": exp.get("policy_version"),
        "control_verifications": exp.get("control_verification_json"),
        "gaps": exp.get("gaps_json", []),
        "generated_at": exp.get("generated_at"),
    }


@router.get("/explanation/{document_id}/narrative")
async def get_explanation_narrative(document_id: str):
    """Get the human-readable narrative for an invoice."""
    exp = repository.get_explanation(document_id)
    if not exp:
        raise HTTPException(status_code=404, detail="No explanation found")
    return {
        "document_id": document_id,
        "explanation_status": exp.get("explanation_status"),
        "narrative": exp.get("narrative_json"),
        "evidence_summary": exp.get("evidence_summary_json", []),
    }


@router.get("/explanation/{document_id}/trace")
async def get_explanation_trace(document_id: str):
    """Get the complete rule trace from the explanation."""
    exp = repository.get_explanation(document_id)
    if not exp:
        raise HTTPException(status_code=404, detail="No explanation found")
    return {
        "document_id": document_id,
        "rule_trace": exp.get("rule_trace_json"),
        "upstream_artifacts": exp.get("upstream_artifacts_json", []),
        "integrity": exp.get("integrity_json"),
    }


@router.get("/audit/{document_id}/reconstruct")
async def reconstruct_decision(document_id: str):
    """
    Decision reconstruction — returns historical record without re-running Stages 1-4.
    PRD Section 17.
    """
    # Get all stored artifacts
    run = repository.get_run(document_id)
    if not run:
        raise HTTPException(status_code=404, detail="Invoice not found")

    validation_history = repository.get_validation_history(document_id)
    decision_history = repository.get_decision_history(document_id)
    explanation = repository.get_explanation(document_id)

    from app.pipeline.stage5.integrity_verifier import verify_audit_chain
    chain_status = verify_audit_chain(limit=50)

    return {
        "document_id": document_id,
        "reconstruction_source": "stored_artifacts",
        "stage1_extraction": run.get("extraction_json"),
        "stage2_match": run.get("stage2_result_json"),
        "stage3_validation": validation_history[0] if validation_history else None,
        "stage4_decision": decision_history[0] if decision_history else None,
        "stage5_explanation": explanation,
        "integrity_status": chain_status.status,
        "chain_records_checked": chain_status.records_checked,
        "chain_breaches": chain_status.breaches,
    }


@router.get("/audit/ledger/status")
async def audit_ledger_status():
    """Get the current audit chain integrity status."""
    from app.pipeline.stage5.integrity_verifier import verify_audit_chain
    result = verify_audit_chain()
    return {
        "status": result.status,
        "records_checked": result.records_checked,
        "first_sequence": result.first_sequence,
        "last_sequence": result.last_sequence,
        "breaches": result.breaches,
    }


@router.get("/audit/ledger/verify")
async def verify_audit_ledger():
    """Run independent verification of the audit ledger hash chain."""
    from app.pipeline.stage5.integrity_verifier import verify_audit_chain
    result = verify_audit_chain(limit=10000)
    return {
        "verification_result": result.status,
        "records_verified": result.records_checked,
        "breaches_found": len(result.breaches),
        "breach_details": result.breaches,
        "chain_range": {
            "first": result.first_sequence,
            "last": result.last_sequence,
        },
    }


# ═══════════════════════════════════════════════════════════
# Enterprise — PO Confirmation (Phase 2)
# ═══════════════════════════════════════════════════════════


@router.get("/invoices/{document_id}/po-suggestions")
async def get_po_suggestions(document_id: str):
    """Ranked PO candidates with evidence for human review."""
    run = repository.get_run(document_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    stage2 = run.get("stage2_result_json") or {}
    candidates = stage2.get("suggested_candidates") or stage2.get("matched_pos") or []
    return {
        "document_id": document_id,
        "match_status": stage2.get("match_status", run.get("stage2_status", "")),
        "po_presence": stage2.get("po_presence", ""),
        "suggestion_mode": stage2.get("suggestion_mode", False),
        "candidates": candidates,
        "confirmed_po": run.get("confirmed_po_number", ""),
    }


@router.post("/invoices/{document_id}/confirm-po")
async def confirm_po(document_id: str, body: dict):
    from app.models.review import POConfirmRequest
    from app.services.review_service import confirm_po_match

    req = POConfirmRequest.model_validate(body)
    try:
        return confirm_po_match(document_id, req.po_number, req.confirmed_by, req.notes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/invoices/{document_id}/reject-po-suggestions")
async def reject_po_suggestions(document_id: str, body: dict):
    from app.models.review import PORejectRequest
    from app.services.review_service import reject_po_suggestions as reject_po_match

    req = PORejectRequest.model_validate(body)
    try:
        return reject_po_match(
            document_id,
            req.manual_po_number,
            req.rejected_by,
            req.notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ═══════════════════════════════════════════════════════════
# Enterprise — Review Operations (Phase 3)
# ═══════════════════════════════════════════════════════════


@router.get("/reviews")
async def list_reviews(
    queue: str | None = Query(None),
    status: str = Query("open"),
    limit: int = Query(50, ge=1, le=200),
):
    items = repository.list_review_work_items(queue=queue, status=status, limit=limit)
    return {"work_items": items, "count": len(items)}


@router.post("/reviews/{document_id}/actions")
async def post_review_action(document_id: str, body: dict):
    from app.models.review import HumanActionRequest
    from app.services.review_service import record_human_action, apply_field_correction_and_rerun

    req = HumanActionRequest.model_validate(body)
    if req.action_type == "FIELD_CORRECTION" and req.field_corrections:
        return apply_field_correction_and_rerun(document_id, req)
    action = record_human_action(document_id, req)
    return {"document_id": document_id, "action": action.model_dump()}


# ═══════════════════════════════════════════════════════════
# Enterprise — Analytics & Vendor Profiles (Phase 4)
# ═══════════════════════════════════════════════════════════


@router.get("/analytics/exceptions")
async def get_exception_analytics():
    return repository.get_exception_analytics()


@router.get("/vendor-profiles/{vendor_id}")
async def get_vendor_profile(vendor_id: str):
    from app.services.vendor_profile_service import get_profile_for_vendor

    profile = get_profile_for_vendor(None, vendor_id=vendor_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Vendor profile not found")
    return profile


@router.put("/vendor-profiles/{vendor_id}")
async def upsert_vendor_profile(vendor_id: str, body: dict):
    body["vendor_id"] = vendor_id
    repository.save_vendor_profile(vendor_id, body)
    return {"vendor_id": vendor_id, "status": "saved"}


# ═══════════════════════════════════════════════════════════
# Master Data Import (CSV / XLSX)
# ═══════════════════════════════════════════════════════════


def _validate_master_data_upload(filename: str | None) -> str:
    if not filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    ext = resolve_upload_extension(filename)
    if ext not in SUPPORTED_UPLOAD_EXTENSIONS:
        supported = ", ".join(SUPPORTED_UPLOAD_EXTENSIONS)
        raise HTTPException(status_code=400, detail=f"Supported: {supported}")
    return ext


@router.post("/master-data/preview")
async def preview_master_data(
    request: Request,
    file: UploadFile = File(...),
    company_id: str = Query("DEFAULT"),
    _user: dict | None = Depends(optional_auth),
):
    """Validate and preview PO master data import without committing."""
    await rate_limit(request, bucket="import", limit=20)
    _validate_master_data_upload(file.filename)

    from app.context.tenant import set_company_id
    from app.services.master_data_importer import MasterDataImporter

    set_company_id(company_id)
    try:
        content = await file.read()
        result = MasterDataImporter().preview(content, file.filename, company_id=company_id)
        return result
    except Exception as exc:
        logger.exception("Master data preview failed")
        raise HTTPException(status_code=500, detail=f"Preview failed: {exc}") from exc


@router.post("/master-data/import")
async def import_master_data(
    request: Request,
    file: UploadFile = File(...),
    company_id: str = Query("DEFAULT"),
    _user: dict | None = Depends(optional_auth),
):
    """Import PO master data (vendors, POs, lines, GRN, references)."""
    await rate_limit(request, bucket="import", limit=10)
    _validate_master_data_upload(file.filename)

    from app.context.tenant import set_company_id
    from app.services.master_data_importer import MasterDataImporter

    set_company_id(company_id)
    try:
        content = await file.read()
        result = MasterDataImporter().commit(content, file.filename, company_id=company_id)
    except Exception as exc:
        logger.exception("Master data import failed")
        from app.db.database import get_connection

        conn = get_connection()
        if hasattr(conn, "rollback"):
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}") from exc
    if not result.get("valid") and not result.get("partial_success"):
        raise HTTPException(status_code=422, detail=result)
    if result.get("review_needed"):
        raise HTTPException(status_code=422, detail=result)
    return result


@router.post("/master-data/import/confirm")
async def confirm_master_data_import(
    request: Request,
    file: UploadFile = File(...),
    company_id: str = Query("DEFAULT"),
    mappings: str = Form("{}"),
    _user: dict | None = Depends(optional_auth),
):
    """Confirm ambiguous column mappings and commit import."""
    await rate_limit(request, bucket="import", limit=10)
    _validate_master_data_upload(file.filename)

    from app.context.tenant import set_company_id
    from app.services.master_data_importer import MasterDataImporter

    set_company_id(company_id)
    try:
        confirmed = json.loads(mappings)
        sheet_mappings = confirmed.get("sheets", confirmed if isinstance(confirmed, list) else [])
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid mappings JSON")

    content = await file.read()
    result = MasterDataImporter().commit(
        content,
        file.filename,
        company_id=company_id,
        confirmed_mappings=sheet_mappings,
    )
    if not result.get("valid") and not result.get("partial_success"):
        raise HTTPException(status_code=422, detail=result)
    return result


@router.post("/master-data/activate/{batch_id}")
async def activate_staged_import(batch_id: str, company_id: str = Query("DEFAULT")):
    """Activate a previously staged import batch."""
    from app.context.tenant import set_company_id
    from app.services.adaptive_importer import AdaptiveImporter

    set_company_id(company_id)
    result = AdaptiveImporter().activate_batch(batch_id, company_id)
    if not result.get("valid") and not result.get("partial_success"):
        raise HTTPException(status_code=422, detail=result)
    return result


@router.post("/master-data/clear")
async def clear_master_data(
    request: Request,
    company_id: str = Query("DEFAULT"),
    scope: str = Query("master", pattern="^(master|all)$"),
    _user: dict | None = Depends(optional_auth),
):
    """Delete master data, or entire database when scope=all (no demo re-seed)."""
    await rate_limit(request, bucket="import", limit=5)
    from app.context.tenant import set_company_id

    set_company_id(company_id)
    if scope == "all":
        result = repository.clear_all_data(company_id=None if company_id == "DEFAULT" else company_id)
        message = "All data cleared (invoices, jobs, master data, imports)."
    else:
        result = repository.clear_master_data(company_id=company_id)
        message = "Master data cleared. Re-upload your PO master file."
    return {"message": message, **result}


@router.get("/master-data/imports")
async def list_master_data_imports(company_id: str = Query("DEFAULT"), limit: int = Query(20)):
    """List recent master data import jobs."""
    imports = repository.list_master_data_imports(company_id=company_id, limit=limit)
    return {"imports": imports, "count": len(imports)}


@router.get("/master-data/source-records")
async def list_source_records(
    company_id: str = Query("DEFAULT"),
    limit: int = Query(100, le=500),
    po_reference_status: str | None = Query(None),
):
    """List imported invoice/transaction source records."""
    records = repository.get_source_records_by_company(
        company_id=company_id,
        limit=limit,
        po_reference_status=po_reference_status,
    )
    return {"records": records, "count": len(records)}


@router.get("/master-data/source-records/{source_record_id}")
async def get_source_record_detail(source_record_id: str):
    """Get a single imported source record."""
    record = repository.get_source_record(source_record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Source record not found")
    return record
