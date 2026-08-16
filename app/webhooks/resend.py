"""Resend inbound email webhook — attachment to Blob + job enqueue."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.config import settings
from app.jobs.inngest_handler import schedule_invoice_job
from app.jobs.job_service import create_job
from app.storage.storage_service import get_storage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _verify_resend_signature(payload: bytes, signature: str | None) -> bool:
    if not settings.resend_webhook_secret:
        return True
    if not signature:
        return False
    expected = hmac.new(
        settings.resend_webhook_secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/resend/inbound")
async def resend_inbound(request: Request, background_tasks: BackgroundTasks):
    """Ingest inbound invoice email with attachment."""
    body = await request.body()
    sig = request.headers.get("svix-signature") or request.headers.get("x-resend-signature")
    if not _verify_resend_signature(body, sig):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    data = await request.json()
    attachments = data.get("attachments") or data.get("data", {}).get("attachments") or []
    if not attachments:
        raise HTTPException(status_code=400, detail="No attachments in email")

    att = attachments[0]
    filename = att.get("filename") or f"email-{uuid.uuid4().hex[:8]}.pdf"
    content_b64 = att.get("content") or att.get("base64", "")
    content = base64.b64decode(content_b64) if content_b64 else b""

    storage = get_storage()
    storage_key, blob_url = await storage.save_upload(filename, content)
    job = create_job(filename=filename, blob_url=blob_url, storage_key=storage_key)
    mode = await schedule_invoice_job(job["job_id"], background_tasks=background_tasks)

    return {
        "status": "accepted",
        "job_id": job["job_id"],
        "processing_mode": mode,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
