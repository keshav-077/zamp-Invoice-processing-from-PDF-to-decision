"""
InvoiceFlow AI — Stage 2: Line-Level Matching Engine

The most critical Stage 2 component. Matches invoice lines to PO lines using:
1. Exact match (SKU / Part Number / Catalog ID)
2. Semantic match (normalized token overlap between descriptions)
3. Quantity alignment
4. Price alignment

Matching must occur at line level, not header level.
"""

import logging
import re
from difflib import SequenceMatcher

from app.models.match import LineMapping

logger = logging.getLogger(__name__)


class LineMatcher:
    """Matches invoice line items to PO line items."""

    def match_lines(
        self,
        invoice_lines: list[dict],
        po_lines: list[dict],
        po_number: str,
    ) -> list[LineMapping]:
        """
        Match invoice lines to PO lines.

        Args:
            invoice_lines: List of invoice line items from extraction.
            po_lines: List of PO line items from database.
            po_number: PO number for reference.

        Returns:
            List of LineMapping objects (one per invoice line).
        """
        if not invoice_lines:
            return []

        if not po_lines:
            # No PO lines to match against
            return [
                LineMapping(
                    invoice_line=i + 1,
                    po_number=po_number,
                    po_line=0,
                    match_type="unmatched",
                    similarity_score=0.0,
                    detail="No PO lines available for matching",
                )
                for i in range(len(invoice_lines))
            ]

        mappings = []
        used_po_lines = set()

        for inv_idx, inv_line in enumerate(invoice_lines):
            best_mapping = self._find_best_po_line(
                inv_idx + 1, inv_line, po_lines, po_number, used_po_lines
            )
            mappings.append(best_mapping)

            # Track used PO lines to prevent double-matching
            if best_mapping.match_type != "unmatched":
                used_po_lines.add(best_mapping.po_line)

        matched = sum(1 for m in mappings if m.match_type != "unmatched")
        logger.info(
            f"Line matching for {po_number}: "
            f"{matched}/{len(invoice_lines)} lines matched"
        )
        return mappings

    def _find_best_po_line(
        self,
        inv_line_num: int,
        inv_line: dict,
        po_lines: list[dict],
        po_number: str,
        used_po_lines: set,
    ) -> LineMapping:
        """Find the best matching PO line for a given invoice line."""
        inv_desc = inv_line.get("description", "") or ""
        inv_qty = inv_line.get("quantity")
        inv_price = inv_line.get("unit_price")
        inv_amount = inv_line.get("amount")

        best_score = 0.0
        best_po_line = None
        best_match_type = "unmatched"
        best_detail = ""

        for po_line in po_lines:
            po_line_num = po_line.get("line_number", 0)
            if po_line_num in used_po_lines:
                continue

            po_desc = po_line.get("description", "")
            po_sku = po_line.get("sku")
            po_qty = po_line.get("quantity")
            po_price = po_line.get("unit_price")

            # --- Score calculation ---
            score = 0.0
            match_type = "semantic"
            details = []

            # 1. Exact SKU match (highest priority)
            if po_sku and inv_desc:
                inv_desc_upper = inv_desc.upper()
                if po_sku.upper() in inv_desc_upper:
                    score += 0.4
                    match_type = "exact"
                    details.append(f"SKU match: {po_sku}")

            # 2. Description similarity
            desc_sim = self._description_similarity(inv_desc, po_desc)
            score += desc_sim * 0.35
            if desc_sim > 0.5:
                details.append(f"Description similarity: {desc_sim:.2f}")

            # 3. Quantity alignment
            if inv_qty is not None and po_qty is not None and po_qty > 0:
                qty_ratio = min(inv_qty, po_qty) / max(inv_qty, po_qty)
                score += qty_ratio * 0.15
                if qty_ratio > 0.8:
                    details.append(f"Quantity match: {inv_qty} vs {po_qty}")

            # 4. Price alignment
            if inv_price is not None and po_price is not None and po_price > 0:
                price_ratio = min(inv_price, po_price) / max(inv_price, po_price)
                score += price_ratio * 0.10
                if price_ratio > 0.9:
                    details.append(f"Price match: {inv_price} vs {po_price}")

            if score > best_score:
                best_score = score
                best_po_line = po_line
                best_match_type = match_type
                best_detail = "; ".join(details) if details else f"Score: {score:.2f}"

        # Apply minimum threshold
        MIN_LINE_SCORE = 0.25
        if best_score < MIN_LINE_SCORE or best_po_line is None:
            return LineMapping(
                invoice_line=inv_line_num,
                po_number=po_number,
                po_line=0,
                match_type="unmatched",
                similarity_score=best_score,
                detail=f"No adequate PO line match (best score: {best_score:.2f})",
            )

        return LineMapping(
            invoice_line=inv_line_num,
            po_number=po_number,
            po_line=best_po_line.get("line_number", 0),
            match_type=best_match_type,
            similarity_score=round(best_score, 3),
            detail=best_detail,
        )

    def _description_similarity(self, desc1: str, desc2: str) -> float:
        """
        Compute description similarity using token overlap + SequenceMatcher.
        """
        if not desc1 or not desc2:
            return 0.0

        # Normalize
        norm1 = self._normalize_description(desc1)
        norm2 = self._normalize_description(desc2)

        tokens1 = set(norm1.split())
        tokens2 = set(norm2.split())

        # Token overlap (Jaccard)
        if tokens1 and tokens2:
            overlap = len(tokens1 & tokens2)
            union = len(tokens1 | tokens2)
            jaccard = overlap / union if union > 0 else 0
        else:
            jaccard = 0

        # SequenceMatcher ratio
        seq_ratio = SequenceMatcher(None, norm1, norm2).ratio()

        # Combined (weighted)
        return (jaccard * 0.5) + (seq_ratio * 0.5)

    def _normalize_description(self, desc: str) -> str:
        """Normalize description for comparison."""
        normalized = desc.upper().strip()
        # Remove common noise words
        noise = {"THE", "A", "AN", "AND", "OR", "FOR", "OF", "IN", "TO", "WITH"}
        tokens = normalized.split()
        tokens = [t for t in tokens if t not in noise]
        # Remove punctuation
        cleaned = " ".join(tokens)
        cleaned = re.sub(r"[^\w\s]", "", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip()
