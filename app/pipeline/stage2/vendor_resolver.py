"""
InvoiceFlow AI — Stage 2: Vendor Resolution Engine

Resolves invoice vendor against the Vendor Master using a 3-layer hierarchy:
1. Exact identifier match (Tax ID, Vendor ID, Supplier Code)
2. Normalized name match (strip suffixes, case-fold)
3. Fuzzy name match (token overlap + Levenshtein)

Rule: Vendor match alone can NEVER select a PO — it's one signal among several.
"""

import logging
import re
from difflib import SequenceMatcher

from app.db import repository
from app.services.vendor_identity import normalize_vendor_name, vendor_names_equivalent

logger = logging.getLogger(__name__)

# Common corporate suffixes to strip during normalization
CORPORATE_SUFFIXES = [
    r"\bllc\b", r"\bltd\b", r"\binc\b", r"\bcorp\b", r"\bcorporation\b",
    r"\bpvt\b", r"\bprivate\b", r"\blimited\b", r"\bco\b", r"\bcompany\b",
    r"\bgroup\b", r"\bservices\b", r"\bsolutions\b", r"\btechnologies\b",
    r"\b&\b", r"\band\b",
]


class VendorResolution:
    """Result of vendor resolution."""
    def __init__(
        self,
        vendor_id: str | None = None,
        vendor_name: str = "",
        match_method: str = "none",
        confidence: float = 0.0,
        evidence: str = "",
    ):
        self.vendor_id = vendor_id
        self.vendor_name = vendor_name
        self.match_method = match_method
        self.confidence = confidence
        self.evidence = evidence


class VendorResolver:
    """Resolves vendor identity using multi-layer matching."""

    def resolve(self, extracted_vendor_name: str | None) -> VendorResolution:
        """
        Resolve extracted vendor name against the Vendor Master.

        Args:
            extracted_vendor_name: Vendor name from Stage 1 extraction.

        Returns:
            VendorResolution with matched vendor ID, method, and confidence.
        """
        if not extracted_vendor_name:
            logger.info("Vendor resolution: no vendor name extracted")
            return VendorResolution(evidence="No vendor name in extraction")

        all_vendors = repository.get_all_vendors()

        # Layer 1: Tax ID / supplier code if extraction ever provides them
        # (reserved for future structured vendor identifiers on invoices)

        # Layer 2: Normalized name match
        result = self._normalized_match(extracted_vendor_name, all_vendors)
        if result:
            return result

        # Layer 2b: Shared identity equivalence (comma/OCR variants)
        result = self._equivalent_name_match(extracted_vendor_name, all_vendors)
        if result:
            return result

        # Layer 3: Fuzzy name match
        result = self._fuzzy_match(extracted_vendor_name, all_vendors)
        if result:
            return result

        logger.info(f"Vendor resolution: no match for '{extracted_vendor_name}'")
        return VendorResolution(
            evidence=f"No vendor match found for: {extracted_vendor_name}"
        )

    def _normalize_name(self, name: str) -> str:
        return normalize_vendor_name(name)

    def _normalized_match(
        self, extracted_name: str, vendors: list[dict]
    ) -> VendorResolution | None:
        """Try matching via normalized names."""
        extracted_norm = self._normalize_name(extracted_name)

        for vendor in vendors:
            if vendor.get("status") != "active":
                continue

            # Match against normalized_name column and canonical name
            db_norm = vendor.get("normalized_name", "")
            vendor_norm = self._normalize_name(vendor["name"])
            extracted_norm = self._normalize_name(extracted_name)
            if extracted_norm == vendor_norm or (
                db_norm and extracted_norm == self._normalize_name(db_norm)
            ):
                logger.info(
                    f"Vendor resolved (normalized): "
                    f"'{extracted_name}' → {vendor['vendor_id']} ({vendor['name']})"
                )
                return VendorResolution(
                    vendor_id=vendor["vendor_id"],
                    vendor_name=vendor["name"],
                    match_method="normalized",
                    confidence=0.90,
                    evidence=f"Normalized name match: '{extracted_name}' → '{vendor['name']}'",
                )

            # Match against aliases
            aliases = vendor.get("aliases", [])
            for alias in aliases:
                alias_norm = self._normalize_name(alias)
                if extracted_norm == alias_norm:
                    logger.info(
                        f"Vendor resolved (alias): "
                        f"'{extracted_name}' → {vendor['vendor_id']} (alias: {alias})"
                    )
                    return VendorResolution(
                        vendor_id=vendor["vendor_id"],
                        vendor_name=vendor["name"],
                        match_method="alias",
                        confidence=0.85,
                        evidence=f"Alias match: '{extracted_name}' → alias '{alias}' → '{vendor['name']}'",
                    )

        return None

    def _equivalent_name_match(
        self, extracted_name: str, vendors: list[dict]
    ) -> VendorResolution | None:
        """Match via shared vendor_names_equivalent (handles OCR comma variants)."""
        for vendor in vendors:
            if vendor.get("status") != "active":
                continue
            if vendor_names_equivalent(extracted_name, vendor.get("name")):
                return VendorResolution(
                    vendor_id=vendor["vendor_id"],
                    vendor_name=vendor["name"],
                    match_method="equivalent",
                    confidence=0.88,
                    evidence=(
                        f"Vendor name equivalent: '{extracted_name}' → '{vendor['name']}'"
                    ),
                )
            for alias in vendor.get("aliases", []):
                if vendor_names_equivalent(extracted_name, alias):
                    return VendorResolution(
                        vendor_id=vendor["vendor_id"],
                        vendor_name=vendor["name"],
                        match_method="alias_equivalent",
                        confidence=0.85,
                        evidence=(
                            f"Vendor alias equivalent: '{extracted_name}' → '{vendor['name']}'"
                        ),
                    )
        return None

    def _fuzzy_match(
        self,
        extracted_name: str,
        vendors: list[dict],
        min_score: float = 0.70,
    ) -> VendorResolution | None:
        """Fuzzy match using token overlap and SequenceMatcher."""
        extracted_norm = self._normalize_name(extracted_name)
        extracted_tokens = set(extracted_norm.split())

        best_match = None
        best_score = 0.0

        for vendor in vendors:
            if vendor.get("status") != "active":
                continue

            # Score against vendor name
            vendor_norm = self._normalize_name(vendor["name"])
            vendor_tokens = set(vendor_norm.split())

            # Token overlap (Jaccard similarity)
            if extracted_tokens and vendor_tokens:
                overlap = len(extracted_tokens & vendor_tokens)
                union = len(extracted_tokens | vendor_tokens)
                token_score = overlap / union if union > 0 else 0
            else:
                token_score = 0

            # SequenceMatcher ratio
            seq_score = SequenceMatcher(None, extracted_norm, vendor_norm).ratio()

            # Combined score (weighted average)
            combined = (token_score * 0.4) + (seq_score * 0.6)

            # Also check aliases
            for alias in vendor.get("aliases", []):
                alias_norm = self._normalize_name(alias)
                alias_seq = SequenceMatcher(None, extracted_norm, alias_norm).ratio()
                alias_tokens = set(alias_norm.split())
                if extracted_tokens and alias_tokens:
                    alias_overlap = len(extracted_tokens & alias_tokens)
                    alias_union = len(extracted_tokens | alias_tokens)
                    alias_token_score = alias_overlap / alias_union if alias_union > 0 else 0
                else:
                    alias_token_score = 0
                alias_combined = (alias_token_score * 0.4) + (alias_seq * 0.6)
                combined = max(combined, alias_combined)

            if combined > best_score:
                best_score = combined
                best_match = vendor

        if best_match and best_score >= min_score:
            logger.info(
                f"Vendor resolved (fuzzy): "
                f"'{extracted_name}' → {best_match['vendor_id']} "
                f"({best_match['name']}, score: {best_score:.2f})"
            )
            return VendorResolution(
                vendor_id=best_match["vendor_id"],
                vendor_name=best_match["name"],
                match_method="fuzzy",
                confidence=round(best_score * 0.85, 2),  # Scale down fuzzy confidence
                evidence=f"Fuzzy match: '{extracted_name}' → '{best_match['name']}' (score: {best_score:.2f})",
            )

        return None
