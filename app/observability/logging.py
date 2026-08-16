"""Structured observability — never log invoice contents or secrets."""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger("invoiceflow.observability")


def log_stage_event(
    *,
    document_id: str,
    job_id: str | None,
    stage: str,
    duration_ms: float,
    status: str,
    error_category: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "document_id": document_id,
        "job_id": job_id,
        "stage": stage,
        "duration_ms": round(duration_ms, 1),
        "status": status,
    }
    if error_category:
        payload["error_category"] = error_category
    logger.info("stage_event %s", json.dumps(payload))


@contextmanager
def stage_timer(document_id: str, stage: str, job_id: str | None = None):
    start = time.perf_counter()
    try:
        yield
        log_stage_event(
            document_id=document_id,
            job_id=job_id,
            stage=stage,
            duration_ms=(time.perf_counter() - start) * 1000,
            status="ok",
        )
    except Exception as exc:
        log_stage_event(
            document_id=document_id,
            job_id=job_id,
            stage=stage,
            duration_ms=(time.perf_counter() - start) * 1000,
            status="error",
            error_category=type(exc).__name__,
        )
        raise
