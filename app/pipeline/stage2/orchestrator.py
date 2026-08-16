"""
InvoiceFlow AI — Stage 2: PO Matching Orchestrator
"""

import logging
import time

from app.models.extraction import InvoiceExtraction
from app.models.evidence import EvidenceProfile
from app.models.match import MatchPackage, POCandidate
from app.db import repository
from app.pipeline.stage2.confidence_gate import evaluate_confidence
from app.pipeline.stage2.po_presence import check_po_presence
from app.pipeline.stage2.candidate_discovery import CandidateDiscovery
from app.pipeline.stage2.vendor_resolver import VendorResolver
from app.pipeline.stage2.po_validator import POValidator
from app.pipeline.stage2.line_matcher import LineMatcher
from app.pipeline.stage2.balance_tracker import BalanceTracker
from app.pipeline.stage2.evidence_scorer import EvidenceScorer
from app.pipeline.stage2.ambiguity_detector import detect_ambiguity
from app.pipeline.stage2.multi_po_resolver import MultiPOResolver
from app.pipeline.stage2.exception_manager import ExceptionManager
from app.pipeline.stage2.match_explanation import attach_explanation
from app.pipeline.policy_loader import load_validation_policy
from app.services.vendor_identity import vendor_names_equivalent

logger = logging.getLogger(__name__)


class Stage2Orchestrator:
    """Orchestrates the complete Stage 2 PO Matching pipeline."""

    def __init__(self):
        self.candidate_discovery = CandidateDiscovery()
        self.vendor_resolver = VendorResolver()
        self.po_validator = POValidator()
        self.line_matcher = LineMatcher()
        self.balance_tracker = BalanceTracker()
        self.evidence_scorer = EvidenceScorer()
        self.exception_manager = ExceptionManager()
        self.multi_po_resolver = MultiPOResolver()
        self._validation_policy = load_validation_policy()

    def match(
        self,
        document_id: str,
        extraction: InvoiceExtraction,
        suggestion_mode: bool = False,
        top_n: int = 10,
        company_id: str = "DEFAULT",
        evidence_profile: EvidenceProfile | None = None,
    ) -> MatchPackage:
        start_time = time.time()
        logger.info("[%s] Stage 2: Starting PO matching", document_id)

        po_value = extraction.po_reference.value
        po_confidence = extraction.po_reference.confidence
        po_status = extraction.po_reference.status
        vendor_name = extraction.vendor_name.value
        invoice_total = extraction.total_amount.value
        invoice_date = extraction.invoice_date.value
        invoice_number = (
            str(extraction.invoice_number.value)
            if extraction.invoice_number and extraction.invoice_number.value
            else None
        )
        typed_refs = []
        for ref in extraction.typed_references:
            if ref.value and ref.confidence >= 0.5:
                typed_refs.append({"type": ref.reference_type, "value": str(ref.value)})
        if po_value and po_confidence >= 0.7:
            if not any(t["value"] == str(po_value) for t in typed_refs):
                typed_refs.append({"type": "order_ref", "value": str(po_value)})

        invoice_lines = [
            {
                "description": li.description,
                "quantity": li.quantity,
                "unit_price": li.unit_price,
                "amount": li.amount,
                "sku": li.sku,
                "uom": li.uom,
                "po_hint": li.po_hint,
            }
            for li in extraction.line_items
        ]

        confidence_action = evaluate_confidence(
            po_value=str(po_value) if po_value else None,
            po_confidence=po_confidence,
            po_status=po_status,
        )

        po_presence = check_po_presence(
            po_value=str(po_value) if po_value else None,
            po_status=po_status,
        )

        if po_presence == "non_po" and not suggestion_mode:
            if evidence_profile and evidence_profile.matchable_signals:
                suggestion_mode = True
                confidence_action = "expand"
            else:
                package = MatchPackage(
                    invoice_id=document_id,
                    match_status="non_po_workflow",
                    confidence_gate_action=confidence_action,
                    po_presence=po_presence,
                    evidence=["No PO reference found — routed to Non-PO workflow"],
                    flags=["non_po_invoice"],
                    suggestion_mode=suggestion_mode,
                    evidence_profile=evidence_profile,
                )
                return self._finalize_package(package, [], start_time)

        if suggestion_mode and po_presence == "non_po":
            confidence_action = "expand"

        vendor_result = self.vendor_resolver.resolve(str(vendor_name) if vendor_name else None)
        invoice_total_float = float(invoice_total) if invoice_total is not None else None
        invoice_currency = str(extraction.currency.value) if extraction.currency.value else None

        require_exact_po = (
            not suggestion_mode
            and bool(po_value)
            and po_presence == "po_invoice"
        )

        candidates = self.candidate_discovery.discover(
            po_value=str(po_value) if po_value else None,
            vendor_id=vendor_result.vendor_id,
            vendor_name=str(vendor_name) if vendor_name else None,
            confidence_action=confidence_action,
            invoice_total=invoice_total_float,
            suggestion_mode=suggestion_mode,
            typed_references=typed_refs,
            company_id=company_id,
            invoice_number=invoice_number,
            require_exact_po=require_exact_po,
        )

        if not candidates:
            if suggestion_mode and vendor_name:
                status = "unmatched"
                evidence = [
                    f"Vendor: {vendor_name} → {vendor_result.evidence}",
                    "No open PO matched the extracted vendor evidence",
                ]
            else:
                status = "waiting_for_po" if po_presence != "non_po" else "non_po_workflow"
                evidence = [
                    f"PO reference: {po_value or 'none on invoice'}",
                    f"Vendor: {vendor_name} → {vendor_result.evidence}",
                    "No matching PO found in imported master data",
                ]
            if suggestion_mode and status != "unmatched":
                evidence.append("Suggestion mode: no candidates — import PO master or confirm manually")
            package = MatchPackage(
                invoice_id=document_id,
                match_status=status,
                confidence_gate_action=confidence_action,
                po_presence=po_presence,
                evidence=evidence,
                flags=["po_not_found"],
                suggestion_mode=suggestion_mode,
                suggested_candidates=[],
                resolved_invoice_vendor_id=vendor_result.vendor_id,
                evidence_profile=evidence_profile,
            )
            return self._finalize_package(package, [], start_time)

        scored_candidates = self._score_candidates(
            document_id=document_id,
            candidates=candidates,
            vendor_result=vendor_result,
            vendor_name=str(vendor_name) if vendor_name else None,
            invoice_lines=invoice_lines,
            invoice_total_float=invoice_total_float,
            invoice_date=invoice_date,
        )

        suggested = scored_candidates[:top_n]
        all_po_flags = [f for c in scored_candidates for f in c.flags]

        po_currency = None
        if candidates:
            po_currency = candidates[0].get("currency")
        vendor_only_mode = invoice_total_float is None and len(invoice_lines) == 0
        ambiguity_status, selected_candidates = detect_ambiguity(
            scored_candidates,
            suggestion_mode=suggestion_mode,
            invoice_total=invoice_total_float,
            invoice_currency=invoice_currency,
            po_currency=po_currency,
            vendor_only_mode=vendor_only_mode,
            po_presence=po_presence,
        )

        multi_po_flags: list[str] = []
        if len(scored_candidates) > 1 and ambiguity_status in (
            "high_confidence_match",
            "matched",
            "ambiguous_match",
        ):
            candidate_mappings = {
                c.po_number: c.line_mappings for c in scored_candidates[:5]
            }
            final_mappings, multi_unmatched = self.multi_po_resolver.resolve(candidate_mappings)
            if len(final_mappings) > 1:
                selected_candidates = []
                for po_num, mappings in final_mappings.items():
                    cand = next((c for c in scored_candidates if c.po_number == po_num), None)
                    if cand:
                        updated = cand.model_copy(deep=True)
                        updated.line_mappings = mappings
                        selected_candidates.append(updated)
                multi_po_flags.append("multi_po_allocation")
                ambiguity_status = "high_confidence_match"

        unmatched_lines = []
        if selected_candidates:
            unmatched_lines = []
            seen_lines: set[int] = set()
            for cand in selected_candidates:
                for m in cand.line_mappings:
                    if m.match_type == "unmatched" and m.invoice_line not in seen_lines:
                        unmatched_lines.append(m.invoice_line)
                        seen_lines.add(m.invoice_line)

        has_grn = False
        po_type = "standard"
        if selected_candidates:
            top = selected_candidates[0]
            po_type = top.po_type or "standard"
            grn_records = repository.get_grn_for_po(top.po_number, company_id=company_id)
            has_grn = len(grn_records) > 0

        grn_cfg = self._validation_policy.get("grn", {})
        grn_required = grn_cfg.get("required_po_types", ["standard"])

        final_status, exception_flags = self.exception_manager.determine_final_state(
            ambiguity_status=ambiguity_status,
            unmatched_lines=unmatched_lines,
            total_lines=len(invoice_lines),
            po_validation_flags=all_po_flags + multi_po_flags,
            balance_flags=[f for c in scored_candidates for f in c.flags],
            has_grn=has_grn,
            po_type=po_type,
            grn_required_types=grn_required,
        )

        provenance = ""
        if selected_candidates:
            if not suggestion_mode and po_presence == "po_invoice":
                provenance = "authoritative_po"
            elif ambiguity_status in ("matched", "high_confidence_match"):
                provenance = "evidence"
            else:
                provenance = "suggestion"

        top_evidence = selected_candidates[0].evidence.copy() if selected_candidates else []
        if exception_flags:
            top_evidence.append(f"Exception flags: {', '.join(exception_flags)}")

        if suggestion_mode and po_presence == "non_po" and not selected_candidates and suggested:
            final_status = "suggested_po_match"
            top_evidence = ["No PO on invoice — ranked suggestions by vendor, lines, and balance"]
            provenance = "suggestion"

        resolved_vendor_id = vendor_result.vendor_id
        vendor_master_status = "master_hit" if resolved_vendor_id else "unresolved"
        if not resolved_vendor_id and selected_candidates:
            top_c = selected_candidates[0]
            if top_c.score.vendor_match > 0 and top_c.vendor_id:
                resolved_vendor_id = top_c.vendor_id
                vendor_master_status = "po_aligned"
                top_evidence = [
                    e
                    for e in top_evidence
                    if "no vendor match" not in e.lower()
                ]
                top_evidence.insert(
                    0,
                    f"Vendor aligned via matched PO master (name equivalent → {top_c.vendor_id})",
                )

        package = MatchPackage(
            invoice_id=document_id,
            match_status=final_status,
            matched_pos=selected_candidates,
            unmatched_lines=unmatched_lines,
            flags=exception_flags,
            evidence=top_evidence,
            processing_time_seconds=round(time.time() - start_time, 2),
            confidence_gate_action=confidence_action,
            po_presence=po_presence,
            suggestion_mode=suggestion_mode,
            suggested_candidates=suggested,
            resolved_invoice_vendor_id=resolved_vendor_id,
            vendor_master_status=vendor_master_status,
            match_provenance=provenance,
            evidence_profile=evidence_profile,
        )
        package = self._finalize_package(package, scored_candidates, start_time)

        repository.save_match_result(
            document_id=document_id,
            match_status=package.match_status,
            match_package_json=package.model_dump_json(),
        )
        return package

    def _finalize_package(
        self,
        package: MatchPackage,
        scored_candidates: list[POCandidate],
        start_time: float,
    ) -> MatchPackage:
        package.processing_time_seconds = round(time.time() - start_time, 2)
        package = attach_explanation(package, scored_candidates)
        return package

    def _score_candidates(
        self,
        document_id: str,
        candidates: list[dict],
        vendor_result,
        vendor_name: str | None,
        invoice_lines: list[dict],
        invoice_total_float: float | None,
        invoice_date,
    ) -> list[POCandidate]:
        scored_candidates = []
        for candidate_po in candidates:
            po_number = candidate_po["po_number"]
            candidate_vendor_id = candidate_po.get("vendor_id", "")

            # Align vendor_id when PO header name matches invoice vendor but IDs diverge
            resolved_id = vendor_result.vendor_id
            if (
                resolved_id
                and candidate_vendor_id != resolved_id
                and vendor_name
                and vendor_names_equivalent(vendor_name, candidate_po.get("vendor_name", ""))
            ):
                candidate_vendor_id = resolved_id

            po_validation = self.po_validator.validate(candidate_po)
            po_lines = candidate_po.get("lines", [])
            line_mappings = self.line_matcher.match_lines(
                invoice_lines=invoice_lines,
                po_lines=po_lines,
                po_number=po_number,
            )
            balance_check = self.balance_tracker.check_balance(candidate_po, invoice_total_float)

            retrieval_method = candidate_po.get("_retrieval_method", "unknown")
            retrieval_confidence = candidate_po.get("_retrieval_confidence", 0.0)
            po_total = candidate_po.get("total_amount", 0)
            po_remaining = po_total - candidate_po.get("previously_invoiced", 0)

            po_vendor_name = candidate_po.get("vendor_name", "")
            name_aligned = bool(
                vendor_name
                and po_vendor_name
                and vendor_names_equivalent(vendor_name, po_vendor_name)
            )
            vendor_confidence = vendor_result.confidence if vendor_result.vendor_id else 0.0
            if vendor_confidence <= 0 and name_aligned:
                vendor_confidence = 0.9

            score_breakdown, evidence_list = self.evidence_scorer.score(
                retrieval_method=retrieval_method,
                retrieval_confidence=retrieval_confidence,
                resolved_vendor_id=resolved_id,
                candidate_vendor_id=candidate_vendor_id,
                vendor_confidence=vendor_confidence,
                line_mappings=line_mappings,
                invoice_total=invoice_total_float,
                po_total=po_total,
                invoice_date=str(invoice_date) if invoice_date else None,
                po_issue_date=candidate_po.get("issue_date", ""),
                po_remaining=po_remaining,
                balance_ok=balance_check.is_within_balance,
                invoice_vendor_name=vendor_name,
                candidate_vendor_name=po_vendor_name,
            )

            full_evidence = [vendor_result.evidence] + evidence_list
            if balance_check.detail:
                full_evidence.append(balance_check.detail)
            if not po_validation.is_valid:
                full_evidence.append(po_validation.reason)

            scored_candidates.append(
                POCandidate(
                    po_number=po_number,
                    vendor_id=candidate_vendor_id,
                    vendor_name=candidate_po.get("vendor_name", ""),
                    score=score_breakdown,
                    line_mappings=line_mappings,
                    flags=list(po_validation.flags) + list(balance_check.flags),
                    evidence=full_evidence,
                    structured_evidence=self.evidence_scorer.build_structured_signals(
                        score_breakdown,
                        retrieval_method,
                        balance_check.is_within_balance,
                        line_mappings,
                    ),
                    retrieval_method=retrieval_method,
                    import_derived=bool(
                        candidate_po.get("_import_derived")
                        or candidate_po.get("metadata", {}).get("import_derived")
                    ),
                    po_status=candidate_po.get("status", "unknown"),
                    po_type=candidate_po.get("po_type", "standard"),
                    remaining_balance=balance_check.remaining,
                )
            )

        scored_candidates.sort(key=lambda c: c.score.total, reverse=True)
        return scored_candidates
