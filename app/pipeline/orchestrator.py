"""
InvoiceFlow AI — Pipeline Orchestrator

The main orchestrator chains all Stage 1 processing steps:
1. Input validation & preprocessing
2. Page classification (multi-page)
3. LLM Call #1 — Primary extraction
4. LLM Call #2 — Independent verification
5. Deterministic arithmetic validation
6. Routing decision

Implements retry-then-degrade logic:
  LLM failure → retry once → if still failing: EXTRACTION_FAILED
  → preserve original → human/ops review
"""

import json
import logging
import time
import uuid
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.models.extraction import InvoiceExtraction
from app.models.verification import VerificationResult
from app.models.arithmetic import ArithmeticResult
from app.models.pipeline import PipelineResult
from app.models.page import PageClassification
from app.pipeline.input_handler import InputHandler, InputValidationError
from app.pipeline.page_classifier import PageClassifier
from app.pipeline.extractor import Extractor
from app.pipeline.verifier import Verifier
from app.models.reconciliation import ReconciliationResult
from app.pipeline.normalizer import normalize_extraction
from app.pipeline.reconciliation import ReconciliationEngine
from app.pipeline.router import Router
from app.pipeline.evidence_profile import build_evidence_profile
from app.pipeline.stage3.contract_gate import validate_contract
from app.models.match import MatchPackage, validation_allowed
from app.models.workflow_state import WorkflowState
from app.pipeline.stage2.orchestrator import Stage2Orchestrator
from app.pipeline.stage2.match_explanation import build_match_explanation
from app.providers.base import LLMProvider, ProviderError
from app.providers.resilience import invoke_with_fallback
from app.context.tenant import get_company_id
from app.db import repository
from app.pipeline.stage3.orchestrator import Stage3Orchestrator
from app.pipeline.stage4.orchestrator import Stage4Orchestrator
from app.pipeline.status_messages import (
    describe_stage2,
    describe_stage3,
    describe_stage4,
    describe_evidence_profile,
    describe_extraction_quality,
)
from app.pipeline.stage5.orchestrator import Stage5Orchestrator

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """
    Orchestrates the complete Stage 1 invoice processing pipeline.

    Each step is timed. All intermediate results are preserved
    in the audit trail. The original document is always kept.
    """

    def __init__(self, provider: LLMProvider):
        self.provider = provider
        self.input_handler = InputHandler()
        self.page_classifier = PageClassifier(provider)
        self.extractor = Extractor(provider)
        self.verifier = Verifier(provider)
        self.arithmetic_validator = ReconciliationEngine()
        self.router = Router()

    async def process_invoice(self, file_path: Path) -> PipelineResult:
        """
        Process a single invoice through the complete Stage 1 pipeline.

        Args:
            file_path: Path to the uploaded invoice file.

        Returns:
            PipelineResult with full audit trail.
        """
        start_time = time.time()
        document_id = str(uuid.uuid4())[:12]

        logger.info(f"[{document_id}] Starting pipeline for: {file_path.name}")

        # Postgres FK constraints require invoice_runs before stage 2–5 child rows.
        repository.ensure_invoice_run_stub(
            document_id=document_id,
            filename=file_path.name,
            original_file_path=str(file_path),
            company_id=get_company_id(),
        )

        # Initialize result with defaults
        result = PipelineResult(
            document_id=document_id,
            filename=file_path.name,
            status="extraction_failed",
            upload_timestamp=datetime.now(timezone.utc),
            original_file_path=str(file_path),
        )

        try:
            # ── Step 1: Input Validation & Preprocessing ──
            logger.info(f"[{document_id}] Step 1: Input validation & preprocessing")
            try:
                all_page_images = self.input_handler.validate_and_preprocess(file_path)
                if all_page_images:
                    scores = [
                        self.input_handler.score_document_quality(img)
                        for img in all_page_images
                    ]
                    result.document_quality_score = float(
                        round(sum(scores) / len(scores), 3)
                    )
            except InputValidationError as e:
                result.status = "extraction_failed"
                result.error_details = f"Input validation failed: {e}"
                result.decision = "EXTRACTION_FAILED"
                result.decision_explanation = [f"❌ {e}"]
                result.processing_time_seconds = time.time() - start_time
                return result

            # ── Step 2: Page Classification ──
            logger.info(f"[{document_id}] Step 2: Page classification")
            pages = await self.page_classifier.classify(all_page_images)
            result.pages = pages

            # Filter to financial/invoice pages (include continuations, exclude legal/signature)
            skip_types = {"terms_and_conditions", "signature_block"}
            invoice_page_indices = [
                p.page_number - 1 for p in pages if p.classification not in skip_types
            ]
            if not invoice_page_indices:
                logger.warning(
                    f"[{document_id}] No financial pages classified — using all pages"
                )
                invoice_images = all_page_images
            else:
                invoice_images = [all_page_images[i] for i in invoice_page_indices]

            logger.info(
                f"[{document_id}] Using {len(invoice_images)}/{len(all_page_images)} "
                f"page(s) for extraction"
            )

            # ── Step 3: LLM Call #1 — Primary Extraction ──
            logger.info(f"[{document_id}] Step 3: Primary extraction (LLM Call #1)")
            extraction = await self._extract_with_retry(invoice_images, document_id)

            if extraction is None:
                result.status = "extraction_failed"
                result.decision = "EXTRACTION_FAILED"
                result.decision_explanation = [
                    "❌ Primary extraction failed after retry",
                    "❌ Original document preserved for manual review",
                ]
                result.processing_time_seconds = time.time() - start_time
                return result

            result.extraction = extraction

            # ── Step 3b: Normalization ──
            logger.info(f"[{document_id}] Step 3b: Normalization")
            extraction = normalize_extraction(extraction)
            result.extraction = extraction

            # ── Step 4: LLM Call #2 — Independent Verification ──
            logger.info(f"[{document_id}] Step 4: Independent verification (LLM Call #2)")
            extraction_json = extraction.model_dump_json(indent=2)
            verification = await self.verifier.verify(
                original_images=all_page_images,  # Send ALL pages, not just invoice pages
                extraction_json=extraction_json,
            )
            result.verification = verification

            # ── Step 5: Reconciliation ──
            logger.info(f"[{document_id}] Step 5: Reconciliation")
            reconciliation = self.arithmetic_validator.reconcile(extraction)
            arithmetic = self.arithmetic_validator.to_arithmetic_result(reconciliation)
            result.arithmetic = arithmetic
            result.reconciliation = reconciliation

            # ── Step 5b: Evidence Profile ──
            logger.info(f"[{document_id}] Step 5b: Building evidence profile")
            evidence_profile = build_evidence_profile(
                extraction, verification, reconciliation
            )
            result.evidence_profile = evidence_profile
            result.workflow_state = WorkflowState.RECONCILED.value

            # ── Step 6: Routing Decision ──
            logger.info(f"[{document_id}] Step 6: Routing decision")
            routing = self.router.route(
                extraction=extraction,
                verification=verification,
                arithmetic=arithmetic,
                reconciliation=reconciliation,
                evidence_profile=evidence_profile,
            )

            result.status = routing.status
            result.extraction_quality = routing.extraction_quality
            result.decision = routing.status.upper()
            result.decision_explanation = (
                describe_extraction_quality(routing.extraction_quality)
                + describe_evidence_profile(evidence_profile)
                + routing.explanations
            )

            can_match = self.router.can_run_matching(extraction, evidence_profile)
            match_package = None

            # ── Step 7: Stage 2 — PO Matching ──
            if can_match:
                result.workflow_state = WorkflowState.PO_RESOLVING.value
                logger.info(f"[{document_id}] Step 7: Stage 2 PO Matching")
                po_ref = extraction.po_reference
                has_trusted_po = (
                    po_ref.value
                    and po_ref.confidence >= 0.85
                    and po_ref.status in ("extracted", "inferred")
                )
                suggestion_mode = not has_trusted_po
                if has_trusted_po:
                    logger.info(f"[{document_id}] Exact PO on invoice — suggestion_mode=False")
                try:
                    stage2 = Stage2Orchestrator()
                    company_id = get_company_id()
                    match_package = stage2.match(
                        document_id=document_id,
                        extraction=extraction,
                        suggestion_mode=suggestion_mode,
                        company_id=company_id,
                        evidence_profile=evidence_profile,
                    )
                    result.stage2_result = match_package
                    result.stage2_status = match_package.match_status
                    result.decision_explanation.extend(describe_stage2(match_package))
                    logger.info(
                        f"[{document_id}] Stage 2 result: {match_package.match_status} "
                        f"({match_package.processing_time_seconds}s)"
                    )

                    # ── Steps 8–10: Stage 3–5 when PO match supports validation ──
                    validation_report = None
                    decision_record = None
                    gate = validate_contract(document_id, match_package)
                    if gate.is_valid and gate.validation_mode in ("full", "limited"):
                        result.workflow_state = WorkflowState.VALIDATING.value
                        logger.info(f"[{document_id}] Step 8: Stage 3 Validation")
                        try:
                            stage3 = Stage3Orchestrator()
                            validation_report = stage3.validate(
                                document_id=document_id,
                                extraction=extraction,
                                match_package=match_package,
                                evidence_profile=evidence_profile,
                            )
                            result.stage3_result = validation_report
                            result.stage3_status = validation_report.overall_state
                            result.decision_explanation.extend(
                                describe_stage3(
                                    validation_report.overall_state,
                                    validation_report.evidence_summary,
                                )
                            )
                            logger.info(
                                f"[{document_id}] Stage 3 result: {validation_report.overall_state} "
                                f"({validation_report.processing_time_seconds}s)"
                            )
                        except Exception as e:
                            logger.error(f"[{document_id}] Stage 3 error: {e}", exc_info=True)
                            result.stage3_status = "stage3_error"

                        if validation_report and result.stage3_status != "stage3_error":
                            logger.info(f"[{document_id}] Step 9: Stage 4 Decision")
                            try:
                                stage4 = Stage4Orchestrator(
                                    auto_approve_limit=settings.auto_approve_limit,
                                    manager_limit=settings.manager_approve_limit,
                                    director_limit=settings.director_approve_limit,
                                    freshness_hours=settings.validation_freshness_hours,
                                )
                                decision_record = stage4.decide(
                                    document_id=document_id,
                                    validation_report=validation_report,
                                )
                                result.stage4_result = decision_record
                                result.stage4_status = decision_record.decision_substate
                                result.stage4_decision = decision_record.decision
                                result.decision_explanation.extend(
                                    describe_stage4(
                                        decision_record.decision,
                                        decision_record.decision_substate,
                                    )
                                )
                                logger.info(
                                    f"[{document_id}] Stage 4 result: "
                                    f"{decision_record.decision}/{decision_record.decision_substate} "
                                    f"({decision_record.processing_time_seconds}s)"
                                )
                            except Exception as e:
                                logger.error(f"[{document_id}] Stage 4 error: {e}", exc_info=True)
                                result.stage4_status = "stage4_error"

                        if decision_record and result.stage4_status != "stage4_error":
                            logger.info(f"[{document_id}] Step 10: Stage 5 Explanation")
                            try:
                                stage5 = Stage5Orchestrator()
                                explanation = stage5.explain(
                                    document_id=document_id,
                                    decision_record=decision_record,
                                    extraction=extraction,
                                    match_package=match_package,
                                    validation_report=validation_report,
                                    verification=verification,
                                    reconciliation=reconciliation,
                                    routing_status=result.status,
                                )
                                result.stage5_result = explanation
                                result.stage5_status = explanation.explanation_status
                                result.stage5_explanation_id = explanation.explanation_id
                                logger.info(
                                    f"[{document_id}] Stage 5 result: "
                                    f"{explanation.explanation_status} "
                                    f"({len(explanation.narrative)} steps, "
                                    f"{explanation.processing_time_seconds}s)"
                                )
                            except Exception as e:
                                logger.error(f"[{document_id}] Stage 5 error: {e}", exc_info=True)
                                fallback = Stage5Orchestrator().explain(
                                    document_id=document_id,
                                    decision_record=decision_record,
                                    extraction=extraction,
                                    match_package=match_package,
                                    validation_report=validation_report,
                                    verification=verification,
                                    reconciliation=reconciliation,
                                    routing_status=result.status,
                                )
                                result.stage5_result = fallback
                                result.stage5_status = fallback.explanation_status or "INCOMPLETE"
                                result.stage5_explanation_id = fallback.explanation_id
                        if decision_record and result.stage4_status != "stage4_error":
                            result.workflow_state = WorkflowState.COMPLETED.value
                        elif validation_report and validation_report.overall_state == "VALIDATED":
                            result.workflow_state = WorkflowState.COMPLETED.value
                    elif gate.is_valid and gate.validation_mode == "none":
                        result.workflow_state = WorkflowState.HUMAN_REVIEW.value
                        logger.info(
                            f"[{document_id}] Stage 3 skipped: contract gate — {gate.reason}"
                        )
                    else:
                        result.workflow_state = WorkflowState.HUMAN_REVIEW.value
                        logger.info(
                            f"[{document_id}] Stage 3 blocked: contract gate — {gate.reason}"
                        )

                except Exception as e:
                    logger.error(f"[{document_id}] Stage 2 error: {e}", exc_info=True)
                    result.stage2_status = "stage2_error"
            else:
                result.workflow_state = WorkflowState.HUMAN_REVIEW.value
                logger.info(f"[{document_id}] Step 7: Stage 2 skipped — no matchable evidence")
                no_evidence_pkg = MatchPackage(
                    invoice_id=document_id,
                    match_status="no_matching_evidence",
                    evidence_profile=evidence_profile,
                    evidence=[
                        "Extraction was unable to provide enough information for PO matching.",
                        "PO matching found 0 candidates.",
                    ],
                    explanation=build_match_explanation(
                        "no_matching_evidence", [], [], evidence_profile
                    ),
                    next_stage="human_review",
                )
                result.stage2_result = no_evidence_pkg
                result.stage2_status = "no_matching_evidence"
                result.decision_explanation.extend(describe_stage2(no_evidence_pkg))

            # ── Review work items (Phase 3) ──
            try:
                from app.services.work_item_service import create_work_items_from_pipeline
                create_work_items_from_pipeline(result)
            except Exception as e:
                logger.warning(f"[{document_id}] Work item creation skipped: {e}")

        except Exception as e:
            logger.error(f"[{document_id}] Unexpected pipeline error: {e}", exc_info=True)
            result.status = "extraction_failed"
            result.error_details = f"Unexpected error: {e}"
            result.decision = "EXTRACTION_FAILED"
            result.decision_explanation = [f"❌ Unexpected error: {e}"]

        # Record processing time
        result.processing_time_seconds = round(time.time() - start_time, 2)
        logger.info(
            f"[{document_id}] Pipeline complete: {result.status} "
            f"in {result.processing_time_seconds}s"
        )

        return result

    async def _extract_with_retry(
        self, images: list[bytes], document_id: str
    ) -> InvoiceExtraction | None:
        """
        Extract using primary provider, falling back to Groq/OpenRouter on failure.
        """
        async def do_extract(provider: LLMProvider) -> InvoiceExtraction:
            extractor = Extractor(provider)
            return await extractor.extract(images)

        try:
            extraction, used = await invoke_with_fallback(
                self.provider,
                f"[{document_id}] extraction",
                do_extract,
            )
            logger.info(f"[{document_id}] Extraction succeeded (provider: {used})")
            return extraction
        except ProviderError as e:
            logger.error(f"[{document_id}] All extraction providers failed: {e}")
            return None

