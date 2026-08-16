"""
InvoiceFlow AI — Verification Data Models

Defines the schema for LLM Call #2 (Independent Verification).
The verifier uses the original document as truth and challenges extraction.
"""

from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


class VerificationIssue(BaseModel):
    """A single discrepancy found by the verification pass."""

    field: str = Field(description="The extraction field name with the issue")
    severity: Literal["high", "medium", "low"] = Field(
        description="Impact severity. 'high' = likely wrong, 'medium' = suspicious, 'low' = minor concern"
    )
    reason: str = Field(description="Human-readable explanation of the discrepancy")


class VerificationResult(BaseModel):
    """
    Result of the independent verification pass (LLM Call #2).

    verification_status:
      - pass: extraction appears correct against original document
      - flag: one or more discrepancies found
      - uncertain: verifier could not determine correctness
      - unavailable: verification LLM call failed (do not claim verification occurred)
    """

    verification_status: Literal["pass", "flag", "uncertain", "unavailable"] = Field(
        default="unavailable",
        description="Overall verification verdict"
    )
    overall_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Verifier's overall confidence in the extraction correctness"
    )
    issues: list[VerificationIssue] = Field(
        default_factory=list,
        description="List of discrepancies found"
    )
