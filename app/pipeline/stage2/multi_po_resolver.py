"""
InvoiceFlow AI — Stage 2: Multi-PO Resolution Engine

Supports: One Invoice → Many POs.
- Maps each invoice line to its best PO line across all candidates
- Detects multi-PO scenarios
- Resolves conflicts (same line → multiple POs)
- Handles partial matches (some lines unmatched)
"""

import logging
from app.models.match import LineMapping

logger = logging.getLogger(__name__)


class MultiPOResolver:
    """Resolves multi-PO scenarios and conflicts."""

    def resolve(
        self,
        candidate_line_mappings: dict[str, list[LineMapping]],
    ) -> tuple[dict[str, list[LineMapping]], list[int]]:
        """
        Resolve multi-PO line assignments.

        Given per-candidate line mappings, determine the final assignment
        of each invoice line to exactly one PO.

        Args:
            candidate_line_mappings: {po_number: [LineMapping, ...]} for each candidate.

        Returns:
            (final_mappings, unmatched_lines)
            - final_mappings: {po_number: [LineMapping, ...]} after conflict resolution
            - unmatched_lines: list of invoice line numbers with no match
        """
        if not candidate_line_mappings:
            return {}, []

        # Collect all line assignments
        # For each invoice line, find the best assignment across all POs
        all_invoice_lines = set()
        line_options: dict[int, list[tuple[str, LineMapping]]] = {}

        for po_number, mappings in candidate_line_mappings.items():
            for mapping in mappings:
                all_invoice_lines.add(mapping.invoice_line)
                if mapping.match_type != "unmatched":
                    if mapping.invoice_line not in line_options:
                        line_options[mapping.invoice_line] = []
                    line_options[mapping.invoice_line].append((po_number, mapping))

        # Assign each line to best PO
        final: dict[str, list[LineMapping]] = {}
        unmatched = []

        for inv_line in sorted(all_invoice_lines):
            if inv_line not in line_options or not line_options[inv_line]:
                unmatched.append(inv_line)
                continue

            # Pick the highest scoring option
            options = line_options[inv_line]
            options.sort(key=lambda x: x[1].similarity_score, reverse=True)
            best_po, best_mapping = options[0]

            if best_po not in final:
                final[best_po] = []
            final[best_po].append(best_mapping)

        # Detect multi-PO scenario
        if len(final) > 1:
            po_list = list(final.keys())
            logger.info(
                f"Multi-PO detected: invoice lines span {len(final)} POs: {po_list}"
            )

        if unmatched:
            logger.info(f"Unmatched lines: {unmatched}")

        return final, unmatched
