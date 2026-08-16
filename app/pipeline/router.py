"""
InvoiceFlow AI — Policy-Driven Routing Engine

Uses config/routing_policy.yaml for thresholds and blocking rules.
Evaluates extraction, verification, and reconciliation outcomes.
Extraction quality is metadata — incomplete extraction does not stop PO matching.
"""

import logging

from app.config import settings
from app.models.evidence import (
    EvidenceProfile,
    ExtractionQuality,
    quality_from_profile,
    to_legacy_routing_status,
)
from app.models.extraction import InvoiceExtraction
from app.models.verification import VerificationResult, VerificationIssue
from app.models.arithmetic import ArithmeticResult
from app.models.reconciliation import ReconciliationResult
from app.pipeline.evidence_profile import can_run_po_resolution
from app.pipeline.policy_loader import load_routing_policy

logger = logging.getLogger(__name__)


class RoutingDecision:
    """Encapsulates a routing decision with status and explanations."""

    def __init__(self):
        self.status: str = "stage1_passed"
        self.explanations: list[str] = []
        self._has_issues = False
        self.extraction_quality: ExtractionQuality = ExtractionQuality.COMPLETE
        self.evidence_profile: EvidenceProfile | None = None
        self.approval_review_flags: list[str] = []

    def flag(self, reason: str) -> None:
        self._has_issues = True
        self.explanations.append(f"⚠️ {reason}")
        logger.info(f"Routing flag: {reason}")

    def pass_check(self, detail: str) -> None:
        self.explanations.append(f"✅ {detail}")

    def fail(self, reason: str) -> None:
        self._has_issues = True
        self.status = "extraction_failed"
        self.extraction_quality = ExtractionQuality.FAILED
        self.explanations.append(f"❌ {reason}")


class Router:
    """Evaluates Stage 1 signals using configurable routing policy."""

    def __init__(self):
        self.policy = load_routing_policy()

    def _threshold(self, field_name: str) -> float:
        thresholds = self.policy.get("thresholds", {})
        if field_name in thresholds:
            return float(thresholds[field_name])
        return settings.get_threshold(field_name)

    def _critical_fields(self) -> list[str]:
        return self.policy.get("critical_fields", settings.critical_fields)

    def _approval_critical_fields(self) -> list[str]:
        return self.policy.get(
            "approval_critical_fields",
            self.policy.get("critical_fields", settings.critical_fields),
        )

    def _minimum_signal_fields(self) -> list[str]:
        po_resolution = self.policy.get("po_resolution", {})
        any_of = po_resolution.get("minimum_signals", {}).get("any_of")
        if any_of:
            return any_of
        return self.policy.get("matching_signals", ["vendor_name", "total_amount"])

    def can_run_matching(
        self,
        extraction: InvoiceExtraction,
        evidence_profile: EvidenceProfile | None = None,
    ) -> bool:
        """Minimum extraction signals to attempt Stage 2 matching (any_of policy)."""
        if evidence_profile is not None:
            return can_run_po_resolution(evidence_profile, self.policy)

        field_map = {
            "vendor_name": extraction.vendor_name,
            "total_amount": extraction.total_amount,
            "line_items": extraction.line_items,
            "po_reference": extraction.po_reference,
            "typed_references": extraction.typed_references,
        }
        for signal in self._minimum_signal_fields():
            if signal == "line_items":
                if extraction.line_items:
                    return True
                continue
            if signal == "typed_references":
                if any(
                    ref.value and ref.status in ("extracted", "inferred")
                    for ref in extraction.typed_references
                ):
                    return True
                continue
            field = field_map.get(signal)
            if field is not None and getattr(field, "value", None) is not None:
                return True
        return False

    def route(
        self,
        extraction: InvoiceExtraction,
        verification: VerificationResult,
        arithmetic: ArithmeticResult,
        reconciliation: ReconciliationResult | None = None,
        evidence_profile: EvidenceProfile | None = None,
    ) -> RoutingDecision:
        decision = RoutingDecision()
        decision.evidence_profile = evidence_profile
        reconciled_ok = False
        if reconciliation:
            allowed = set(self.policy.get("non_blocking_reconciliation", []))
            allowed |= set(self.policy.get("review_reconciliation", []))
            reconciled_ok = reconciliation.overall_status in allowed
        verification_ok = verification.verification_status == "pass"

        hard_failed = False
        if verification.verification_status == "unavailable":
            # Verification unavailable is a flag, not hard stop for PO matching
            decision.flag("Independent verification could not be performed (LLM #2 failure)")

        self._check_critical_fields(
            extraction, decision, reconciled_ok=reconciled_ok, verification_ok=verification_ok
        )
        self._check_verification(verification, decision)
        if reconciliation:
            self._check_reconciliation(reconciliation, decision)
        else:
            self._check_arithmetic(arithmetic, decision)

        if evidence_profile:
            decision.extraction_quality = quality_from_profile(
                evidence_profile, hard_failed=decision.status == "extraction_failed"
            )
        elif decision.status == "extraction_failed":
            decision.extraction_quality = ExtractionQuality.FAILED
        elif decision._has_issues:
            decision.extraction_quality = ExtractionQuality.PARTIAL
        else:
            decision.extraction_quality = ExtractionQuality.COMPLETE

        decision.status = to_legacy_routing_status(
            decision.extraction_quality,
            has_review_flags=decision._has_issues,
        )

        if decision.extraction_quality == ExtractionQuality.COMPLETE and not decision._has_issues:
            decision.pass_check("Extraction complete — approval fields satisfied")
        elif evidence_profile and evidence_profile.matchable_signals:
            decision.pass_check(
                f"Partial extraction — matchable signals: {', '.join(evidence_profile.matchable_signals)}"
            )
        elif evidence_profile and not evidence_profile.matchable_signals:
            decision.explanations.append(
                "⚠️ Insufficient extraction evidence for PO matching"
            )

        logger.info(
            f"Routing decision: {decision.status} quality={decision.extraction_quality.value} "
            f"({len(decision.explanations)} items)"
        )
        return decision

    def _effective_confidence(
        self, field_name: str, confidence: float, reconciled_ok: bool, verification_ok: bool
    ) -> float:
        boost_cfg = self.policy.get("confidence_boost_when_reconciled", {})
        boost_fields = boost_cfg.get("fields", ["invoice_date", "total_amount"])
        boost = float(boost_cfg.get("boost_amount", 0.05))
        if reconciled_ok and verification_ok and field_name in boost_fields:
            return min(1.0, confidence + boost)
        return confidence

    def _check_critical_fields(
        self,
        extraction: InvoiceExtraction,
        decision: RoutingDecision,
        reconciled_ok: bool = False,
        verification_ok: bool = False,
    ) -> None:
        field_map = {
            "vendor_name": extraction.vendor_name,
            "invoice_number": extraction.invoice_number,
            "invoice_date": extraction.invoice_date,
            "currency": extraction.currency,
            "total_amount": extraction.total_amount,
        }

        for field_name in self._approval_critical_fields():
            field = field_map.get(field_name)
            if field is None:
                decision.flag(f"Approval field '{field_name}' not in extraction schema")
                continue

            threshold = self._threshold(field_name)

            if field.value is None or field.status == "not_found":
                decision.flag(
                    f"Approval field '{field_name}' missing (status: {field.status}) — "
                    "validation/approval risk, PO matching may still proceed"
                )
                continue

            if field.status == "uncertain":
                decision.flag(
                    f"Approval field '{field_name}' is uncertain "
                    f"(value: {field.value}, confidence: {field.confidence:.2f})"
                )
                continue

            inferred_cfg = self.policy.get("inferred_currency", {})
            if (
                field_name == "currency"
                and field.status in inferred_cfg.get("allowed_statuses", ["inferred", "extracted"])
                and field.confidence >= float(inferred_cfg.get("min_confidence", 0.85))
                and isinstance(field.value, str)
                and len(field.value.strip()) == 3
            ):
                decision.pass_check(
                    f"Field '{field_name}': {field.value} "
                    f"(inferred from document symbol, confidence: {field.confidence:.2f})"
                )
                continue

            effective = self._effective_confidence(
                field_name, field.confidence, reconciled_ok, verification_ok
            )
            if effective < threshold:
                decision.flag(
                    f"Approval field '{field_name}' below confidence threshold "
                    f"({field.confidence:.2f} < {threshold:.2f}, value: {field.value})"
                )
            else:
                decision.pass_check(
                    f"Field '{field_name}': {field.value} "
                    f"(confidence: {field.confidence:.2f} ≥ {threshold:.2f})"
                )

        for field_name, field in {
            "subtotal": extraction.subtotal,
            "tax_amount": extraction.tax_amount,
            "due_date": extraction.due_date,
            "due_date_terms": extraction.due_date_terms,
            "po_reference": extraction.po_reference,
        }.items():
            if field.value is not None and field.status in ("extracted", "inferred"):
                decision.pass_check(f"Field '{field_name}': {field.value} (confidence: {field.confidence:.2f})")

        for charge in extraction.extra_charges:
            decision.pass_check(
                f"Extra charge '{charge.label}' ({charge.category}): {charge.amount} "
                f"(confidence: {charge.confidence:.2f})"
            )

    def _check_reconciliation(
        self, reconciliation: ReconciliationResult, decision: RoutingDecision
    ) -> None:
        status = reconciliation.overall_status
        blocking = set(self.policy.get("blocking_reconciliation", ["failed"]))

        passed = [c for c in reconciliation.checks if c.status == "pass"]
        if passed:
            decision.pass_check(f"Reconciliation: {len(passed)} check(s) passed")

        if status in ("reconciled", "reconciled_with_inferred_charges"):
            decision.pass_check(f"Totals reconciled ({status})")
            if reconciliation.inferred_charges:
                for charge in reconciliation.inferred_charges:
                    decision.pass_check(
                        f"Inferred charge: {charge.get('label')} = {charge.get('amount')}"
                    )
        elif status == "residual_review":
            decision.flag(
                f"Reconciliation residual review: unexplained difference "
                f"of {reconciliation.residual_amount:.2f} — does not block PO matching"
            )
        elif status in blocking:
            for check in reconciliation.checks:
                if check.status == "fail":
                    decision.flag(f"Reconciliation failed: {check.detail}")
        elif status == "partial":
            decision.pass_check("Reconciliation partial — some checks skipped")

    def _is_actionable_verification_issue(self, issue: VerificationIssue) -> bool:
        blocking_fields = set(self.policy.get("blocking_verification_fields", []))
        non_blocking = set(self.policy.get("non_blocking_fields", []))

        if issue.field in non_blocking:
            return False
        if issue.field not in blocking_fields and issue.severity != "high":
            return False
        return True

    def _check_verification(
        self, verification: VerificationResult, decision: RoutingDecision
    ) -> None:
        if decision.status == "extraction_failed":
            return

        actionable = [i for i in verification.issues if self._is_actionable_verification_issue(i)]
        informational = [i for i in verification.issues if i not in actionable]

        for issue in informational:
            decision.pass_check(
                f"Verification note on '{issue.field}' (non-blocking): {issue.reason}"
            )

        if verification.verification_status == "pass" or (
            verification.verification_status == "flag" and not actionable
        ):
            decision.pass_check(
                f"Independent verification passed (confidence: {verification.overall_confidence:.2f})"
            )
        elif verification.verification_status == "flag":
            issues_desc = "; ".join(
                f"{i.field} ({i.severity}): {i.reason}" for i in actionable
            )
            decision.flag(f"Verification flagged discrepancies: {issues_desc}")
        elif verification.verification_status == "uncertain":
            decision.flag(
                f"Verification uncertain (confidence: {verification.overall_confidence:.2f})"
            )

    def _check_arithmetic(
        self, arithmetic: ArithmeticResult, decision: RoutingDecision
    ) -> None:
        if arithmetic.overall_status == "pass":
            passed = [c for c in arithmetic.checks if c.status == "pass"]
            decision.pass_check(f"All arithmetic checks passed ({len(passed)} checks)")
        elif arithmetic.overall_status == "fail":
            for check in arithmetic.checks:
                if check.status == "fail":
                    decision.flag(f"Arithmetic check failed: {check.detail}")
        elif arithmetic.overall_status == "partial":
            passed = [c for c in arithmetic.checks if c.status == "pass"]
            decision.pass_check(f"Arithmetic: {len(passed)} passed (partial)")
