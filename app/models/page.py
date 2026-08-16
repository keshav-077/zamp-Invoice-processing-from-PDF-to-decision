"""
InvoiceFlow AI — Page Classification Data Models

Defines the schema for multi-page document triage.
Only pages classified as 'line_items' are sent to extraction.
"""

from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


class PageClassification(BaseModel):
    """Classification of a single document page."""

    page_number: int = Field(ge=1, description="1-indexed page number")
    classification: Literal[
        "line_items",
        "terms_and_conditions",
        "signature_block",
        "attachment",
        "other"
    ] = Field(
        description=(
            "line_items: invoice header/line-item content. "
            "terms_and_conditions: legal/contractual info. "
            "signature_block: signature/approval page. "
            "attachment: supporting documents. "
            "other: anything that doesn't fit."
        )
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Classification confidence"
    )
