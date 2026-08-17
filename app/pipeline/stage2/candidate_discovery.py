"""
InvoiceFlow AI — Stage 2: Candidate Discovery Engine

Bounded evidence-based retrieval — no global PO broadcast.
"""

import logging
import re
from difflib import SequenceMatcher

from app.db import repository
from app.pipeline.policy_loader import load_matching_policy
from app.services.vendor_identity import normalize_vendor_name

logger = logging.getLogger(__name__)


class CandidateDiscovery:
    """Finds candidate POs through ordered retrieval strategies."""

    def __init__(self):
        self._policy = load_matching_policy()
        self._max_candidates = self._policy.get("retrieval", {}).get("max_candidates", 20)
        self._allow_broadcast = self._policy.get("retrieval", {}).get("allow_broadcast", False)

    def discover(
        self,
        po_value: str | None,
        vendor_id: str | None,
        vendor_name: str | None,
        confidence_action: str,
        invoice_total: float | None = None,
        suggestion_mode: bool = False,
        typed_references: list[dict] | None = None,
        company_id: str = "DEFAULT",
        invoice_number: str | None = None,
        require_exact_po: bool = False,
    ) -> list[dict]:
        candidates: list[dict] = []
        seen_po_numbers: set[str] = set()

        def _add(po: dict, method: str | None = None, confidence: float | None = None) -> None:
            po_number = po["po_number"]
            if po_number in seen_po_numbers:
                return
            po = dict(po)
            if method:
                po["_retrieval_method"] = method
            if confidence is not None:
                po["_retrieval_confidence"] = confidence
            if "lines" not in po:
                po["lines"] = repository.get_po_lines(po_number)
            candidates.append(po)
            seen_po_numbers.add(po_number)

        # 1. Imported transaction history (source_records) by invoice number
        if invoice_number and vendor_name:
            for record in repository.search_source_records_by_invoice_number(
                invoice_number, vendor_name, company_id
            ):
                from app.services.import_po_mirror import source_record_as_po_candidate

                po = source_record_as_po_candidate(record)
                if po:
                    _add(po, "source_record_invoice", 0.88)

        # 2. Typed reference lookup (order_ref, contract_ref, etc.)
        for ref in typed_references or []:
            ref_type = ref.get("type", "order_ref")
            ref_value = ref.get("value")
            if not ref_value:
                continue
            for po in repository.search_pos_by_reference(ref_type, str(ref_value), company_id):
                _add(po, po.get("_retrieval_method", "reference"), po.get("_retrieval_confidence", 0.9))

        # 3. Exact / normalized PO number (when present on invoice)
        if po_value:
            for po in repository.search_pos_by_number(po_value):
                _add(po, "exact", 1.0)
            if not any(c.get("_retrieval_method") == "exact" for c in candidates):
                normalized = self._normalize_po_number(po_value)
                for po in self._search_normalized(normalized, company_id):
                    _add(po, "normalized", 0.85)

        # 4. Vendor identity — skip when trusted PO on invoice was not found in master
        if (vendor_id or vendor_name) and not (
            require_exact_po and po_value and not any(
                c.get("_retrieval_method") in ("exact", "normalized", "reference", "source_record_po_hint")
                for c in candidates
            )
        ):
            for po in repository.search_open_pos_by_vendor_identity(
                vendor_id, vendor_name, company_id
            ):
                method = po.get("_retrieval_method", "vendor_search")
                conf = po.get("_retrieval_confidence", 0.7)
                _add(po, method, conf)

        # 5. Vendor + remaining amount heuristic (partial invoices OK)
        if suggestion_mode and (vendor_id or vendor_name) and invoice_total is not None:
            for po in self.discover_by_vendor_amount(
                vendor_id=vendor_id,
                vendor_name=vendor_name,
                invoice_total=invoice_total,
                company_id=company_id,
            ):
                _add(
                    po,
                    po.get("_retrieval_method", "vendor_amount"),
                    po.get("_retrieval_confidence", 0.5),
                )

        # 6. Fuzzy PO recovery only when a PO-like value was extracted
        if po_value and confidence_action == "expand" and not candidates:
            for po in self._fuzzy_po_search(po_value, company_id):
                _add(po, "fuzzy", po.get("_fuzzy_score", 0.4))

        # Cap candidate set — never broadcast all open POs unless explicitly allowed
        if not candidates and self._allow_broadcast and confidence_action == "expand":
            logger.warning("Broadcast fallback enabled by policy — loading all open POs")
            for po in repository.get_all_open_pos(company_id)[: self._max_candidates]:
                _add(po, "broadcast", 0.1)

        candidates.sort(key=lambda p: p.get("_retrieval_confidence", 0), reverse=True)
        capped = candidates[: self._max_candidates]
        logger.info("Candidate discovery: %s candidate(s) found", len(capped))
        return capped

    def discover_by_vendor_amount(
        self,
        vendor_id: str | None,
        invoice_total: float,
        vendor_name: str | None = None,
        company_id: str = "DEFAULT",
    ) -> list[dict]:
        """Match open POs by vendor identity + invoice fits within PO remaining."""
        tolerance = self._policy.get("retrieval", {}).get("vendor_amount_tolerance_pct", 0.15)
        vendor_pos = repository.search_open_pos_by_vendor_identity(
            vendor_id, vendor_name, company_id
        )
        results = []
        for po in vendor_pos:
            remaining = float(po.get("total_amount", 0)) - float(po.get("previously_invoiced", 0))
            if remaining <= 0:
                continue
            # Invoice must fit within remaining (partial usage is valid)
            if invoice_total <= remaining * (1 + tolerance):
                po = dict(po)
                po["lines"] = repository.get_po_lines(po["po_number"])
                po["_retrieval_method"] = "vendor_amount"
                if invoice_total <= remaining:
                    po["_retrieval_confidence"] = 0.85
                else:
                    over_pct = (invoice_total - remaining) / remaining
                    po["_retrieval_confidence"] = max(0.3, 0.85 - over_pct * 2)
                results.append(po)
        results.sort(key=lambda p: p.get("_retrieval_confidence", 0), reverse=True)
        capped = results[:10]

        uva = self._policy.get("unique_vendor_amount_match", {})
        if uva.get("enabled", True) and len(capped) == 1:
            tight_tol = float(uva.get("max_tolerance_pct", 0.02))
            po = capped[0]
            remaining = float(po.get("total_amount", 0)) - float(po.get("previously_invoiced", 0))
            if remaining > 0 and abs(invoice_total - remaining) <= remaining * tight_tol:
                po["_retrieval_method"] = "unique_vendor_amount"
                po["_retrieval_confidence"] = 0.95

        return capped

    def _normalize_po_number(self, po_value: str) -> str:
        return re.sub(r"[\-\s\.\#]", "", po_value.upper())

    def _search_normalized(self, normalized: str, company_id: str) -> list[dict]:
        results = []
        for po in repository.get_all_open_pos(company_id):
            po_norm = re.sub(r"[\-\s\.\#]", "", po["po_number"].upper())
            if po_norm == normalized:
                po = dict(po)
                po["lines"] = repository.get_po_lines(po["po_number"])
                results.append(po)
        return results

    def _fuzzy_po_search(
        self, po_value: str, company_id: str, min_similarity: float = 0.6
    ) -> list[dict]:
        normalized_input = self._normalize_po_number(po_value)
        scored = []
        for po in repository.get_all_open_pos(company_id):
            po_norm = self._normalize_po_number(po["po_number"])
            ratio = SequenceMatcher(None, normalized_input, po_norm).ratio()
            if ratio >= min_similarity:
                po = dict(po)
                po["_fuzzy_score"] = ratio
                po["lines"] = repository.get_po_lines(po["po_number"])
                scored.append(po)
        scored.sort(key=lambda x: x.get("_fuzzy_score", 0), reverse=True)
        return scored[:5]
