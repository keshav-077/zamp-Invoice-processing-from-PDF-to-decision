"""
InvoiceFlow AI — Stage 3: Validation Orchestrator

Chains all Stage 3 steps:
  1. Contract gate (validate input)
  2. Build validation context (immutable snapshot)
  3. Run applicable validation engines (independent)
  4. Collect evidence and findings
  5. Apply control aggregation policy
  6. Build controls (HOLD/BLOCK records)
  7. Persist validation run
  8. Return ValidationReport
"""

import logging
import time
from datetime import datetime

from app.models.extraction import InvoiceExtraction
from app.models.evidence import EvidenceProfile
from app.models.match import MatchPackage
from app.models.validation import (
    ValidationReport, ValidationCheck, SourceSnapshots, RevalidationInfo,
)
from app.db import repository
from app.pipeline.stage3.contract_gate import validate_contract
from app.pipeline.stage3.validation_context import build_context
from app.pipeline.stage3.amount_validator import validate_amount
from app.pipeline.stage3.tax_validator import validate_tax
from app.pipeline.stage3.duplicate_detector import detect_duplicates
from app.pipeline.stage3.vendor_validator import validate_vendor
from app.pipeline.stage3.receipt_validator import validate_receipt
from app.pipeline.stage3.budget_validator import validate_budget
from app.pipeline.stage3.fraud_detector import detect_fraud_signals
from app.pipeline.stage3.control_aggregator import aggregate_controls
from app.pipeline.stage3.extraction_field_validator import check_extraction_fields

logger = logging.getLogger(__name__)

# Engine registry — maps check_id to validator function
ENGINE_REGISTRY = {
    "amount_variance": validate_amount,
    "tax_validation": validate_tax,
    "duplicate_detection": detect_duplicates,
    "vendor_validation": validate_vendor,
    "receipt_match": validate_receipt,
    "budget_tolerance": validate_budget,
    # fraud_signals handled separately (returns tuple)
}


class Stage3Orchestrator:
    """Orchestrates the complete Stage 3 Validation pipeline."""

    def validate(
        self,
        document_id: str,
        extraction: InvoiceExtraction,
        match_package: MatchPackage,
        evidence_profile: EvidenceProfile | None = None,
    ) -> ValidationReport:
        """
        Run the complete Stage 3 validation pipeline.

        Args:
            document_id: Document ID from Stage 1
            extraction: Stage 1 extraction result
            match_package: Stage 2 match result

        Returns:
            ValidationReport for Stage 4
        """
        start_time = time.time()
        started_at = datetime.utcnow().isoformat()
        logger.info(f"[{document_id}] Stage 3: Starting validation")

        # ── Step 1: Contract Gate ──
        logger.info(f"[{document_id}] Step 1: Contract gate")
        gate_result = validate_contract(document_id, match_package)

        if gate_result.validation_mode == "none":
            # Cannot validate — return VALIDATION_INCOMPLETE
            report = ValidationReport(
                invoice_id=document_id,
                processing_state="COMPLETED",
                overall_state="VALIDATION_INCOMPLETE",
                reason_codes=["CONTRACT_GATE_NO_VALIDATION"],
                evidence_summary=[
                    f"Stage 2 state: {match_package.match_status}",
                    gate_result.reason or "Validation cannot proceed",
                ],
                processing_time_seconds=round(time.time() - start_time, 2),
                started_at=started_at,
                completed_at=datetime.utcnow().isoformat(),
                next_action="MANUAL_REVIEW",
                source_snapshots=SourceSnapshots(
                    stage1=f"S1-{document_id}",
                    stage2=f"S2-{document_id}",
                ),
                revalidation=RevalidationInfo(
                    eligible=True, trigger="initial"
                ),
            )
            self._persist_report(report)
            return report

        if not gate_result.is_valid:
            report = ValidationReport(
                invoice_id=document_id,
                processing_state="FAILED",
                overall_state="VALIDATION_INCOMPLETE",
                reason_codes=["CONTRACT_FAILURE"],
                evidence_summary=[gate_result.reason],
                processing_time_seconds=round(time.time() - start_time, 2),
                started_at=started_at,
                completed_at=datetime.utcnow().isoformat(),
                next_action="INVESTIGATE",
            )
            self._persist_report(report)
            return report

        # ── Step 2: Build Validation Context ──
        logger.info(f"[{document_id}] Step 2: Building validation context")
        ctx = build_context(document_id, extraction, match_package)

        # ── Step 3: Run Validation Engines ──
        logger.info(
            f"[{document_id}] Step 3: Running {len(gate_result.engines_to_run)} engines"
        )
        checks: dict[str, ValidationCheck] = {}
        fraud_signals_list = []

        for engine_id in gate_result.engines_to_run:
            try:
                if engine_id == "fraud_signals":
                    fraud_check, fraud_sigs = detect_fraud_signals(ctx)
                    checks[engine_id] = fraud_check
                    fraud_signals_list = fraud_sigs
                elif engine_id in ENGINE_REGISTRY:
                    checks[engine_id] = ENGINE_REGISTRY[engine_id](ctx)
                else:
                    logger.warning(f"Unknown engine: {engine_id}")
                    checks[engine_id] = ValidationCheck(
                        check_id=engine_id,
                        status="UNAVAILABLE",
                        reason_code="ENGINE_NOT_FOUND",
                        evidence=[f"Validation engine '{engine_id}' not found"],
                    )
            except Exception as e:
                logger.error(
                    f"[{document_id}] Engine {engine_id} failed: {e}",
                    exc_info=True,
                )
                checks[engine_id] = ValidationCheck(
                    check_id=engine_id,
                    status="UNAVAILABLE",
                    reason_code="ENGINE_ERROR",
                    evidence=[f"Engine error: {str(e)}"],
                )

        extraction_check, extraction_reasons = check_extraction_fields(
            extraction, evidence_profile, match_status=match_package.match_status
        )
        checks["extraction_completeness"] = extraction_check

        # ── Step 4: Control Aggregation ──
        logger.info(f"[{document_id}] Step 4: Control aggregation")
        overall_state, reason_codes, controls = aggregate_controls(
            checks=checks,
            fraud_signals=fraud_signals_list,
            match_status=match_package.match_status,
        )
        reason_codes = list(dict.fromkeys(reason_codes + extraction_reasons))

        # ── Step 5: Build Evidence Summary ──
        evidence_summary = []
        evidence_summary.append(f"Stage 2 match: {match_package.match_status}")
        if ctx.matched_po_number:
            evidence_summary.append(f"Matched PO: {ctx.matched_po_number}")
        if ctx.vendor_name:
            evidence_summary.append(f"Vendor: {ctx.vendor_name}")

        for check_id, check in checks.items():
            status_icon = {
                "PASS": "✅", "FLAG": "⚠️", "FAIL": "❌",
                "NOT_APPLICABLE": "➖", "UNAVAILABLE": "❓",
            }.get(check.status, "?")
            evidence_summary.append(
                f"{status_icon} {check_id}: {check.status}"
                + (f" ({check.reason_code})" if check.reason_code else "")
            )

        if controls:
            evidence_summary.append(
                f"Controls: {len(controls)} active "
                f"({', '.join(c.reason_code for c in controls)})"
            )

        # ── Step 6: Build Report ──
        completed_at = datetime.utcnow().isoformat()
        report = ValidationReport(
            invoice_id=document_id,
            processing_state="COMPLETED",
            overall_state=overall_state,
            reason_codes=reason_codes,
            checks=checks,
            controls=controls,
            evidence_summary=evidence_summary,
            fraud_signals=fraud_signals_list,
            policy_version="AP-2026.08.1",
            source_snapshots=SourceSnapshots(
                stage1=f"S1-{document_id}",
                stage2=f"S2-{document_id}",
                po=ctx.po_ref,
                vendor=ctx.vendor_ref,
                grn=ctx.grn_ref,
                extraction={
                    "invoice_number": extraction.invoice_number.model_dump(),
                    "invoice_date": extraction.invoice_date.model_dump(),
                    "vendor_name": extraction.vendor_name.model_dump(),
                    "total_amount": extraction.total_amount.model_dump(),
                    "currency": extraction.currency.model_dump(),
                },
            ),
            revalidation=RevalidationInfo(
                eligible=overall_state in ("HOLD", "VALIDATION_INCOMPLETE"),
                trigger="initial",
            ),
            processing_time_seconds=round(time.time() - start_time, 2),
            started_at=started_at,
            completed_at=completed_at,
            next_action=self._determine_next_action(overall_state),
        )

        logger.info(
            f"[{document_id}] Stage 3 complete: {overall_state} "
            f"({len(checks)} checks, {len(controls)} controls, "
            f"{report.processing_time_seconds}s)"
        )

        # ── Step 7: Persist ──
        self._persist_report(report)

        return report

    def _determine_next_action(self, overall_state: str) -> str:
        """Determine the next action based on overall state."""
        return {
            "VALIDATED": "STAGE4_DECISION",
            "REVIEW_REQUIRED": "STAGE4_DECISION",
            "HOLD": "EXCEPTION_RESOLUTION",
            "BLOCKED": "EXCEPTION_RESOLUTION",
            "VALIDATION_INCOMPLETE": "WAIT_OR_REVALIDATE",
        }.get(overall_state, "STAGE4_DECISION")

    def _persist_report(self, report: ValidationReport) -> None:
        """Persist the validation report to the audit trail."""
        try:
            import json
            repository.save_validation_run(
                validation_run_id=report.validation_run_id,
                document_id=report.invoice_id,
                overall_state=report.overall_state,
                report_json=report.model_dump_json(),
                reason_codes_json=json.dumps(report.reason_codes),
                checks_json=json.dumps({
                    k: v.model_dump() for k, v in report.checks.items()
                }),
                controls_json=json.dumps([c.model_dump() for c in report.controls]),
                evidence_json=json.dumps(report.evidence_summary),
                fraud_signals_json=json.dumps([s.model_dump() for s in report.fraud_signals]),
                policy_version=report.policy_version,
                source_snapshots_json=report.source_snapshots.model_dump_json(),
                started_at=report.started_at,
                completed_at=report.completed_at,
                parent_run_id=report.revalidation.parent_run_id,
                trigger=report.revalidation.trigger,
            )
        except Exception as e:
            logger.error(f"Failed to persist validation run: {e}", exc_info=True)
