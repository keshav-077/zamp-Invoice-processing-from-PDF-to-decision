"""
InvoiceFlow AI — Arithmetic Validation Data Models

Defines the schema for deterministic Python-based arithmetic checks.
These checks are never performed by the LLM — they use exact Decimal math.
"""

from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


class ArithmeticCheck(BaseModel):
    """Result of a single arithmetic validation check."""

    check_name: str = Field(description="Name of the arithmetic check performed")
    expected: float | None = Field(
        default=None,
        description="Expected value based on computation"
    )
    actual: float | None = Field(
        default=None,
        description="Actual value from the extraction"
    )
    status: Literal["pass", "fail", "skipped"] = Field(
        default="skipped",
        description="pass: values match within tolerance. fail: mismatch. skipped: required fields missing."
    )
    detail: str = Field(
        default="",
        description="Human-readable explanation of the check result"
    )


class ArithmeticResult(BaseModel):
    """Aggregate result of all arithmetic validation checks."""

    overall_status: Literal["pass", "fail", "partial"] = Field(
        default="pass",
        description="pass: all checks passed. fail: at least one failed. partial: some skipped, none failed."
    )
    checks: list[ArithmeticCheck] = Field(
        default_factory=list,
        description="Individual check results"
    )
