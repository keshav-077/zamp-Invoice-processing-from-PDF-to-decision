"""Review work items and human action request models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field
import uuid


class ReviewWorkItem(BaseModel):
    """Operational review queue item."""

    work_item_id: str = Field(default_factory=lambda: f"RWI-{uuid.uuid4().hex[:10].upper()}")
    document_id: str
    queue: str
    reason_codes: list[str] = Field(default_factory=list)
    priority: Literal["LOW", "NORMAL", "HIGH", "URGENT"] = "NORMAL"
    sla_due_at: str = ""
    status: Literal["open", "assigned", "completed"] = "open"
    assigned_to: str = ""
    stage1_status: str = ""
    stage2_status: str = ""
    stage4_decision: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class HumanActionRequest(BaseModel):
    """Request body for review actions."""

    action_type: Literal["APPROVE", "REJECT", "OVERRIDE", "COMMENT", "FIELD_CORRECTION"]
    actor_id: str
    detail: str = ""
    outcome: str = ""
    field_corrections: dict[str, object] | None = None


class POConfirmRequest(BaseModel):
    po_number: str
    confirmed_by: str
    notes: str = ""


class PORejectRequest(BaseModel):
    rejected_by: str
    notes: str = ""
    manual_po_number: str | None = None
