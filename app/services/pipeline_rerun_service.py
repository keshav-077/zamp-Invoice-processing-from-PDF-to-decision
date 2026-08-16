"""Shared pipeline re-run path for corrections, PO confirmation, and review completion."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.config import settings
from app.db import repository
from app.models.extraction import InvoiceExtraction
from app.models.match import MatchPackage, POCandidate, validation_allowed
from app.models.pipeline import PipelineResult
from app.models.reconciliation import ReconciliationResult
from app.models.verification import VerificationResult
from app.pipeline.evidence_profile import build_evidence_profile
from app.pipeline.stage3.contract_gate import validate_contract
from app.pipeline.normalizer import normalize_extraction
from app.pipeline.policy_loader import load_decision_policy
from app.pipeline.reconciliation import ReconciliationEngine
from app.pipeline.router import Router
from app.pipeline.stage2.orchestrator import Stage2Orchestrator
from app.pipeline.stage2.line_matcher import LineMatcher
from app.pipeline.stage2.evidence_scorer import EvidenceScorer
from app.pipeline.stage2.balance_tracker import BalanceTracker
from app.pipeline.stage3.orchestrator import Stage3Orchestrator
from app.pipeline.stage4.orchestrator import Stage4Orchestrator
from app.pipeline.stage5.orchestrator import Stage5Orchestrator
from app.pipeline.status_messages import describe_stage2, describe_stage3, describe_stage4
from app.services.work_item_service import create_work_items_from_pipeline

logger = logging.getLogger(__name__)


@dataclass
class RerunResult:
    document_id: str
    status: str
    stage2_status: str
    stage3_status: str
    stage4_decision: str
    stage5_status: str
    match_package: MatchPackage | None = None
    decision_explanation: list[str] | None = None


def _suggestion_mode_for(extraction: InvoiceExtraction, force_exact: bool = False) -> bool:
    if force_exact:
        return False
    po_ref = extraction.po_reference
    has_trusted_po = (
        po_ref.value
        and po_ref.confidence >= 0.85
        and po_ref.status in ("extracted", "inferred")
    )
    return not has_trusted_po


def _build_confirmed_match_package(
    document_id: str,
    extraction: InvoiceExtraction,
    po_number: str,
    confirmed_by: str,
) -> MatchPackage:
    """Build a real match package after human PO confirmation with line matching."""
    po = repository.get_po(po_number)
    if not po:
        raise ValueError(f"PO {po_number} not found")

    invoice_lines = [
        {
            "description": li.description,
            "quantity": li.quantity,
            "unit_price": li.unit_price,
            "amount": li.amount,
        }
        for li in extraction.line_items
    ]
    po_lines = po.get("lines", [])
    line_mappings = LineMatcher().match_lines(invoice_lines, po_lines, po_number)
    invoice_total = (
        float(extraction.total_amount.value)
        if extraction.total_amount.value is not None
        else None
    )
    balance = BalanceTracker().check_balance(po, invoice_total)
    po_total = po.get("total_amount", 0)
    po_remaining = po_total - po.get("previously_invoiced", 0)

    score_breakdown, evidence = EvidenceScorer().score(
        retrieval_method="exact",
        retrieval_confidence=1.0,
        resolved_vendor_id=po.get("vendor_id"),
        candidate_vendor_id=po.get("vendor_id", ""),
        vendor_confidence=1.0,
        line_mappings=line_mappings,
        invoice_total=invoice_total,
        po_total=po_total,
        invoice_date=str(extraction.invoice_date.value) if extraction.invoice_date.value else None,
        po_issue_date=po.get("issue_date", ""),
        po_remaining=po_remaining,
        balance_ok=balance.is_within_balance,
    )

    candidate = POCandidate(
        po_number=po_number,
        vendor_id=po.get("vendor_id", ""),
        vendor_name=po.get("vendor_name", ""),
        score=score_breakdown,
        line_mappings=line_mappings,
        flags=list(balance.flags),
        evidence=[f"Human confirmed PO {po_number} by {confirmed_by}"] + evidence,
        po_status=po.get("status", "open"),
        po_type=po.get("po_type", "standard"),
        remaining_balance=balance.remaining,
    )

    return MatchPackage(
        invoice_id=document_id,
        match_status="matched",
        matched_pos=[candidate],
        evidence=[f"PO {po_number} confirmed by {confirmed_by}"],
        suggestion_mode=False,
        match_provenance="human_confirmed",
        resolved_invoice_vendor_id=po.get("vendor_id"),
    )


def _stage4_orchestrator() -> Stage4Orchestrator:
    policy = load_decision_policy()
    limits = policy.get("limits", {})
    return Stage4Orchestrator(
        auto_approve_limit=limits.get("auto_approve_limit", settings.auto_approve_limit),
        manager_limit=limits.get("manager_approve_limit", settings.manager_approve_limit),
        director_limit=limits.get("director_approve_limit", settings.director_approve_limit),
        freshness_hours=limits.get("validation_freshness_hours", settings.validation_freshness_hours),
    )


def rerun_stages_2_through_5(
    document_id: str,
    extraction: InvoiceExtraction,
    *,
    match_package: MatchPackage | None = None,
    force_exact_po: bool = False,
    routing_status: str | None = None,
    verification: VerificationResult | None = None,
    reconciliation: ReconciliationResult | None = None,
) -> RerunResult:
    """Re-run Stages 2–5 after correction or PO confirmation."""
    extraction = normalize_extraction(extraction)
    reconciler = ReconciliationEngine()
    reconciliation = reconciliation or reconciler.reconcile(extraction)
    arithmetic = reconciler.to_arithmetic_result(reconciliation)

    if verification is None:
        verification = VerificationResult(verification_status="unavailable", overall_confidence=0)

    evidence_profile = build_evidence_profile(extraction, verification, reconciliation)
    routing = Router().route(
        extraction, verification, arithmetic, reconciliation, evidence_profile
    )
    status = routing_status or routing.status
    explanations = list(routing.explanations)

    if match_package is None:
        stage2 = Stage2Orchestrator()
        match_package = stage2.match(
            document_id,
            extraction,
            suggestion_mode=_suggestion_mode_for(extraction, force_exact=force_exact_po),
            evidence_profile=evidence_profile,
        )

    explanations.extend(describe_stage2(match_package))
    stage3_status = ""
    stage4_decision = ""
    stage5_status = ""
    decision_record = None

    gate = validate_contract(document_id, match_package)
    if gate.is_valid and gate.validation_mode in ("full", "limited"):
        stage3 = Stage3Orchestrator()
        validation_report = stage3.validate(
            document_id, extraction, match_package, evidence_profile
        )
        stage3_status = validation_report.overall_state
        explanations.extend(
            describe_stage3(validation_report.overall_state, validation_report.evidence_summary)
        )

        stage4 = _stage4_orchestrator()
        decision_record = stage4.decide(document_id, validation_report)
        stage4_decision = decision_record.decision
        explanations.extend(
            describe_stage4(decision_record.decision, decision_record.decision_substate)
        )

        stage5 = Stage5Orchestrator()
        explanation = stage5.explain(
            document_id,
            decision_record,
            extraction=extraction,
            match_package=match_package,
            validation_report=validation_report,
        )
        stage5_status = explanation.explanation_status

    repository.update_run_after_rerun(
        document_id=document_id,
        extraction=extraction,
        reconciliation=reconciliation,
        arithmetic=arithmetic,
        status=status,
        decision_explanation=explanations,
        stage2_result=match_package,
        stage2_status=match_package.match_status,
        stage3_status=stage3_status,
        stage4_decision=stage4_decision,
        stage5_status=stage5_status,
    )

    pipeline_stub = PipelineResult(
        document_id=document_id,
        filename="",
        status=status,
        stage2_status=match_package.match_status,
        stage3_status=stage3_status,
        stage4_decision=stage4_decision,
        stage4_status=stage4_decision,
        reconciliation=reconciliation,
    )
    create_work_items_from_pipeline(pipeline_stub)

    return RerunResult(
        document_id=document_id,
        status=status,
        stage2_status=match_package.match_status,
        stage3_status=stage3_status,
        stage4_decision=stage4_decision,
        stage5_status=stage5_status,
        match_package=match_package,
        decision_explanation=explanations,
    )


def complete_review_work_items(document_id: str) -> None:
    """Mark open review work items for a document as completed."""
    items = repository.list_review_work_items(status="open")
    for item in items:
        if item.get("document_id") == document_id:
            repository.complete_review_work_item(item["work_item_id"])
