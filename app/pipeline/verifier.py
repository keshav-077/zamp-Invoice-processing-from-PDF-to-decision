"""
InvoiceFlow AI — Independent Verification (LLM Call #2)

Uses a Vision-Language Model to independently verify the extraction
produced by LLM Call #1 against the original document.

The verifier must NOT blindly trust the extraction. Its purpose is to
challenge it using the original document as the sole source of truth.

If the verification LLM call fails, verification is marked as 'unavailable'
rather than claiming it occurred.
"""

import json
import logging
from app.models.verification import VerificationResult, VerificationIssue
from app.providers.base import LLMProvider, ProviderError
from app.providers.resilience import invoke_with_fallback

logger = logging.getLogger(__name__)

VERIFICATION_PROMPT = """You are an independent invoice verification system. Your job is to CHALLENGE an extraction result by comparing it against the original invoice document.

## YOUR ROLE
You are the REVIEWER, not the extractor. Do NOT trust the provided extraction. Use the original document image(s) as the SOLE source of truth.

## VERIFICATION CHECKS (VALUE-FIRST)
Focus on whether extracted VALUES match what is visible — NOT on label wording.
For each extracted field, verify:
1. Does the extracted VALUE (number, date, text) ACTUALLY APPEAR in the document?
2. For amounts: does 332.80 appear as the total/grand total/amount due? Label text does not matter.
3. For dates: is the extracted date value correct for invoice_date or due_date?
4. Are there COMPETING numeric values the extractor might have picked wrong? (subtotal vs total)
5. For extra_charges: do shipping/handling/discount amounts match visible fee lines?
6. For due_date_terms: verify the raw payment terms text if due_date is inferred — do NOT fail because only terms appear.
7. For due_date: "Expiry Date", "Payment Due", and "Due Date" are equivalent — do NOT flag label differences.
8. For currency: inferring USD from "$" is acceptable — do NOT flag as high severity.
9. For po_reference: missing PO on document is NOT a verification failure.

## SEVERITY LEVELS
- "high": The value is likely WRONG (different value in document, wrong field mapping, or critical mismatch)
- "medium": The value is SUSPICIOUS (ambiguous source, partial visibility, competing candidates)
- "low": Minor concern (formatting difference, minor rounding, inferred field)

## IMPORTANT RULES
- If the extraction looks correct and matches the document, say "pass".
- If you find discrepancies, list each one with field, severity, and reason.
- If you cannot determine correctness (e.g., document is too blurry), say "uncertain".
- Be specific in your reasons. Don't just say "mismatch" — explain what you see.
- Do NOT confirm values by re-extracting — actually verify against what's visible.

## OUTPUT FORMAT
Return ONLY valid JSON:
{
  "verification_status": "pass" | "flag" | "uncertain",
  "overall_confidence": 0.0 to 1.0,
  "issues": [
    {
      "field": "field_name",
      "severity": "high" | "medium" | "low",
      "reason": "Specific explanation of the discrepancy"
    }
  ]
}

If no issues found, return empty issues list with status "pass".
"""


class Verifier:
    """Runs LLM Call #2 — Independent verification against the original document."""

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    async def verify(
        self,
        original_images: list[bytes],
        extraction_json: str,
    ) -> VerificationResult:
        """
        Independently verify extraction against original invoice images.

        Args:
            original_images: Original (unfiltered) page images as PNG bytes.
            extraction_json: JSON string of the extraction from LLM Call #1.

        Returns:
            VerificationResult with status, confidence, and issues.
        """
        logger.info(f"Starting independent verification on {len(original_images)} page(s)")

        async def do_verify(provider: LLMProvider) -> str:
            return await provider.verify_invoice(
                images=original_images,
                extraction_json=extraction_json,
                prompt=VERIFICATION_PROMPT,
            )

        try:
            raw_response, used = await invoke_with_fallback(
                self.provider,
                "verification",
                do_verify,
            )
            logger.info(f"Verification completed via provider: {used}")
            return self._parse_verification(raw_response)

        except ProviderError as e:
            # If verification fails, DO NOT claim it occurred
            logger.error(f"Verification LLM call failed: {e}")
            return VerificationResult(
                verification_status="unavailable",
                overall_confidence=0.0,
                issues=[
                    VerificationIssue(
                        field="system",
                        severity="high",
                        reason=f"Verification could not be performed: {e}",
                    )
                ],
            )

    def _parse_verification(self, raw_json: str) -> VerificationResult:
        """Parse and validate the verification response."""
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            logger.warning("Verification JSON parse failed — marking as uncertain")
            return VerificationResult(
                verification_status="uncertain",
                overall_confidence=0.0,
                issues=[
                    VerificationIssue(
                        field="system",
                        severity="medium",
                        reason="Verification response was not valid JSON",
                    )
                ],
            )

        if not isinstance(data, dict):
            return VerificationResult(
                verification_status="uncertain",
                overall_confidence=0.0,
                issues=[
                    VerificationIssue(
                        field="system",
                        severity="medium",
                        reason="Unexpected verification response format",
                    )
                ],
            )

        # Parse status
        status = data.get("verification_status", "uncertain")
        valid_statuses = {"pass", "flag", "uncertain"}
        if status not in valid_statuses:
            status = "uncertain"

        # Parse confidence
        try:
            confidence = float(data.get("overall_confidence", 0.0))
            confidence = max(0.0, min(1.0, confidence))
        except (ValueError, TypeError):
            confidence = 0.0

        # Parse issues
        issues = []
        for issue_data in data.get("issues", []):
            if not isinstance(issue_data, dict):
                continue
            try:
                severity = issue_data.get("severity", "medium")
                if severity not in {"high", "medium", "low"}:
                    severity = "medium"

                issues.append(
                    VerificationIssue(
                        field=str(issue_data.get("field", "unknown")),
                        severity=severity,
                        reason=str(issue_data.get("reason", "No reason provided")),
                    )
                )
            except Exception as e:
                logger.warning(f"Skipping malformed verification issue: {e}")
                continue

        # If issues with high severity exist but status is "pass", override to "flag"
        has_high_severity = any(i.severity == "high" for i in issues)
        if has_high_severity and status == "pass":
            status = "flag"
            logger.warning("Overriding verification status to 'flag' — high severity issues present")

        result = VerificationResult(
            verification_status=status,
            overall_confidence=confidence,
            issues=issues,
        )

        logger.info(
            f"Verification result: status={result.verification_status}, "
            f"confidence={result.overall_confidence:.2f}, "
            f"issues={len(result.issues)}"
        )
        return result
