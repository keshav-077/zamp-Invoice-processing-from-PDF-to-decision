"""
InvoiceFlow AI — Reconciliation Data Models

Replaces rigid subtotal+tax=total with flexible reconciliation outcomes.
"""

from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


class ReconciliationCheck(BaseModel):
    """Result of a single reconciliation check."""

    check_name: str = Field(description="Name of the check performed")
    expected: float | None = Field(default=None)
    actual: float | None = Field(default=None)
    status: Literal["pass", "fail", "skipped", "review"] = Field(default="skipped")
    detail: str = Field(default="")


class ReconciliationResult(BaseModel):
    """Aggregate reconciliation outcome for Stage 1 routing."""

    overall_status: Literal[
        "reconciled",
        "reconciled_with_inferred_charges",
        "residual_review",
        "partial",
        "failed",
    ] = Field(default="failed")
    checks: list[ReconciliationCheck] = Field(default_factory=list)
    inferred_charges: list[dict] = Field(
        default_factory=list,
        description="Charges inferred from unexplained residual"
    )
    residual_amount: float | None = Field(default=None)
