"""Inngest durable job handler for invoice processing."""

from __future__ import annotations

import logging

from fastapi import BackgroundTasks

from app.config import settings
from app.jobs.job_service import run_job

logger = logging.getLogger(__name__)

_inngest_client = None


def get_inngest():
    global _inngest_client
    if _inngest_client is not None:
        return _inngest_client
    if not settings.inngest_event_key:
        return None
    try:
        import inngest
        from inngest import Inngest

        client = Inngest(app_id=settings.inngest_app_id, event_key=settings.inngest_event_key)

        @client.create_function(
            fn_id="process-invoice",
            trigger=inngest.TriggerEvent(event="invoice/process"),
        )
        async def process_invoice(ctx, step):
            job_id = ctx.event.data.get("job_id")
            if not job_id:
                raise ValueError("job_id required")

            async def _run():
                return await run_job(job_id)

            return await step.run("run-pipeline", _run)

        _inngest_client = client
        return client
    except ImportError:
        logger.warning("inngest package not installed — using background task fallback")
        return None


async def schedule_invoice_job(
    job_id: str,
    background_tasks: BackgroundTasks | None = None,
) -> str:
    """
    Queue invoice processing without blocking the HTTP response.

    Returns processing mode: inngest | background | inline
    """
    client = get_inngest()
    if client is not None:
        import inngest

        await client.send(inngest.Event(name="invoice/process", data={"job_id": job_id}))
        logger.info("Job %s queued via Inngest", job_id)
        return "inngest"

    if background_tasks is not None:
        background_tasks.add_task(run_job, job_id)
        logger.info("Job %s scheduled as background task", job_id)
        return "background"

    await run_job(job_id)
    logger.info("Job %s completed inline", job_id)
    return "inline"


# Backward-compatible alias
async def enqueue_invoice_job(
    job_id: str,
    background_tasks: BackgroundTasks | None = None,
) -> None:
    await schedule_invoice_job(job_id, background_tasks=background_tasks)
