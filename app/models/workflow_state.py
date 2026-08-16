"""
InvoiceFlow AI — Explicit workflow state machine (Spec Section 28).
"""

from enum import Enum


class WorkflowState(str, Enum):
    EXTRACTING = "EXTRACTING"
    EXTRACTED = "EXTRACTED"
    VERIFIED = "VERIFIED"
    RECONCILED = "RECONCILED"
    RECONCILIATION_REVIEW = "RECONCILIATION_REVIEW"
    PO_RESOLVING = "PO_RESOLVING"
    VALIDATING = "VALIDATING"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    COMPLETED = "COMPLETED"
