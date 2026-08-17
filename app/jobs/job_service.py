"""Processing job persistence and orchestration."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.db import repository
from app.pipeline.orchestrator import PipelineOrchestrator
from app.providers.factory import get_provider
from app.storage.storage_service import get_storage

logger = logging.getLogger(__name__)

STAGE_ORDER = ["stage1", "stage2", "stage3", "stage4", "stage5"]


def create_job(filename: str, blob_url: str, storage_key: str) -> dict:
    job_id = f"JOB-{uuid.uuid4().hex[:12].upper()}"
    now = datetime.now(timezone.utc).isoformat()
    repository.save_processing_job(
        job_id=job_id,
        filename=filename,
        blob_url=blob_url,
        storage_key=storage_key,
        status="queued",
        stage_status={s: "pending" for s in STAGE_ORDER},
        created_at=now,
        updated_at=now,
    )
    return repository.get_processing_job(job_id)


def _set_stages(job_id: str, stage: str, status: str, document_id: str | None = None) -> None:
    job = repository.get_processing_job(job_id)
    if not job:
        return
    stages = dict(job.get("stage_status") or {})
    stages[stage] = status
    for s in STAGE_ORDER:
        if s not in stages:
            stages[s] = "pending"
    repository.update_processing_job(
        job_id,
        stage_status=stages,
        document_id=document_id,
    )


async def run_job(job_id: str) -> dict:
    """Idempotent invoice processing for a queued job."""
    job = repository.get_processing_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")
    if job.get("status") == "completed" and job.get("document_id"):
        logger.info("Job %s already completed — skipping duplicate delivery", job_id)
        return job

    repository.update_processing_job(job_id, status="processing")
    try:
        storage = get_storage()
        storage_key = job.get("storage_key") or job.get("blob_url", "")
        file_path = await storage.get_local_path(storage_key)

        _set_stages(job_id, "stage1", "active")
        provider = get_provider()
        orchestrator = PipelineOrchestrator(provider)
        result = await orchestrator.process_invoice(Path(file_path))

        repository.save_run(result)
        repository.update_processing_job(
            job_id,
            status="completed",
            document_id=result.document_id,
            stage_status={s: "done" for s in STAGE_ORDER},
        )
        return repository.get_processing_job(job_id)
    except Exception as exc:
        logger.error("Job %s failed: %s", job_id, exc, exc_info=True)
        repository.update_processing_job(
            job_id,
            status="failed",
            error_message=str(exc),
        )
        raise
