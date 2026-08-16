"""
InvoiceFlow AI — Deterministic Arithmetic Validation

Pure Python validation — NO LLM involved.
Uses Decimal arithmetic with configurable rounding tolerance.

Checks:
1. subtotal + tax = total
2. line_item.quantity × line_item.unit_price = line_item.amount (per line)
3. sum(line_items.amount) ≈ subtotal
4. total > 0 (sanity)
5. tax ≤ total (sanity)
"""

import logging
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from app.models.extraction import InvoiceExtraction
from app.models.arithmetic import ArithmeticCheck, ArithmeticResult
from app.config import settings

logger = logging.getLogger(__name__)


class ArithmeticValidator:
    """Runs deterministic arithmetic validation on extracted invoice data."""

    def __init__(self, tolerance: float | None = None):
        self.tolerance = Decimal(str(tolerance or settings.arithmetic_tolerance))

    def validate(self, extraction: InvoiceExtraction) -> ArithmeticResult:
        """
        Run all arithmetic checks on the extraction result.

        Args:
            extraction: The parsed InvoiceExtraction from LLM Call #1.

        Returns:
            ArithmeticResult with individual check results and overall status.
        """
        checks = []

        # Check 1: subtotal + tax = total
        checks.append(self._check_subtotal_plus_tax(extraction))

        # Check 2: line item amounts (quantity × unit_price = amount)
        checks.extend(self._check_line_item_amounts(extraction))

        # Check 3: sum of line items ≈ subtotal
        checks.append(self._check_line_items_sum(extraction))

        # Check 4: total > 0
        checks.append(self._check_positive_total(extraction))

        # Check 5: tax ≤ total
        checks.append(self._check_tax_not_exceeds_total(extraction))

        # Determine overall status
        statuses = [c.status for c in checks]
        if "fail" in statuses:
            overall = "fail"
        elif "skipped" in statuses and "pass" in statuses:
            overall = "partial"
        elif all(s == "skipped" for s in statuses):
            overall = "partial"
        else:
            overall = "pass"

        result = ArithmeticResult(overall_status=overall, checks=checks)

        logger.info(
            f"Arithmetic validation: {overall} "
            f"({sum(1 for c in checks if c.status == 'pass')} pass, "
            f"{sum(1 for c in checks if c.status == 'fail')} fail, "
            f"{sum(1 for c in checks if c.status == 'skipped')} skipped)"
        )
        return result

    def _to_decimal(self, value) -> Decimal | None:
        """Safely convert a value to Decimal."""
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return None

    def _values_match(self, a: Decimal, b: Decimal) -> bool:
        """Check if two Decimal values match within tolerance."""
        return abs(a - b) <= self.tolerance

    def _check_subtotal_plus_tax(self, extraction: InvoiceExtraction) -> ArithmeticCheck:
        """Check: subtotal + tax_amount = total_amount."""
        subtotal = self._to_decimal(extraction.subtotal.value)
        tax = self._to_decimal(extraction.tax_amount.value)
        total = self._to_decimal(extraction.total_amount.value)

        if subtotal is None or tax is None or total is None:
            missing = []
            if subtotal is None:
                missing.append("subtotal")
            if tax is None:
                missing.append("tax_amount")
            if total is None:
                missing.append("total_amount")
            return ArithmeticCheck(
                check_name="subtotal_plus_tax_equals_total",
                status="skipped",
                detail=f"Missing fields: {', '.join(missing)}",
            )

        expected = subtotal + tax
        if self._values_match(expected, total):
            return ArithmeticCheck(
                check_name="subtotal_plus_tax_equals_total",
                expected=float(expected),
                actual=float(total),
                status="pass",
                detail=f"{subtotal} + {tax} = {expected} ≈ {total} ✓",
            )
        else:
            return ArithmeticCheck(
                check_name="subtotal_plus_tax_equals_total",
                expected=float(expected),
                actual=float(total),
                status="fail",
                detail=f"{subtotal} + {tax} = {expected} ≠ {total} (difference: {abs(expected - total)})",
            )

    def _check_line_item_amounts(self, extraction: InvoiceExtraction) -> list[ArithmeticCheck]:
        """Check: quantity × unit_price = amount for each line item."""
        checks = []

        for i, item in enumerate(extraction.line_items, 1):
            qty = self._to_decimal(item.quantity)
            price = self._to_decimal(item.unit_price)
            amount = self._to_decimal(item.amount)

            if qty is None or price is None or amount is None:
                checks.append(ArithmeticCheck(
                    check_name=f"line_item_{i}_amount",
                    status="skipped",
                    detail=f"Line {i}: Missing quantity, unit_price, or amount",
                ))
                continue

            expected = qty * price
            if self._values_match(expected, amount):
                checks.append(ArithmeticCheck(
                    check_name=f"line_item_{i}_amount",
                    expected=float(expected),
                    actual=float(amount),
                    status="pass",
                    detail=f"Line {i}: {qty} × {price} = {expected} ≈ {amount} ✓",
                ))
            else:
                checks.append(ArithmeticCheck(
                    check_name=f"line_item_{i}_amount",
                    expected=float(expected),
                    actual=float(amount),
                    status="fail",
                    detail=f"Line {i}: {qty} × {price} = {expected} ≠ {amount}",
                ))

        return checks

    def _check_line_items_sum(self, extraction: InvoiceExtraction) -> ArithmeticCheck:
        """Check: sum of line item amounts ≈ subtotal."""
        if not extraction.line_items:
            return ArithmeticCheck(
                check_name="line_items_sum_equals_subtotal",
                status="skipped",
                detail="No line items to validate",
            )

        subtotal = self._to_decimal(extraction.subtotal.value)
        if subtotal is None:
            return ArithmeticCheck(
                check_name="line_items_sum_equals_subtotal",
                status="skipped",
                detail="Subtotal not available for comparison",
            )

        line_sum = Decimal("0")
        skipped_lines = 0
        for item in extraction.line_items:
            amount = self._to_decimal(item.amount)
            if amount is not None:
                line_sum += amount
            else:
                skipped_lines += 1

        if skipped_lines == len(extraction.line_items):
            return ArithmeticCheck(
                check_name="line_items_sum_equals_subtotal",
                status="skipped",
                detail="No line item amounts available",
            )

        if self._values_match(line_sum, subtotal):
            return ArithmeticCheck(
                check_name="line_items_sum_equals_subtotal",
                expected=float(line_sum),
                actual=float(subtotal),
                status="pass",
                detail=f"Sum of line items: {line_sum} ≈ subtotal: {subtotal} ✓"
                + (f" ({skipped_lines} lines skipped)" if skipped_lines else ""),
            )
        else:
            return ArithmeticCheck(
                check_name="line_items_sum_equals_subtotal",
                expected=float(line_sum),
                actual=float(subtotal),
                status="fail",
                detail=f"Sum of line items: {line_sum} ≠ subtotal: {subtotal} (difference: {abs(line_sum - subtotal)})",
            )

    def _check_positive_total(self, extraction: InvoiceExtraction) -> ArithmeticCheck:
        """Sanity check: total should be positive."""
        total = self._to_decimal(extraction.total_amount.value)

        if total is None:
            return ArithmeticCheck(
                check_name="positive_total",
                status="skipped",
                detail="Total amount not available",
            )

        if total > 0:
            return ArithmeticCheck(
                check_name="positive_total",
                actual=float(total),
                status="pass",
                detail=f"Total {total} > 0 ✓",
            )
        else:
            return ArithmeticCheck(
                check_name="positive_total",
                actual=float(total),
                status="fail",
                detail=f"Total {total} is not positive",
            )

    def _check_tax_not_exceeds_total(self, extraction: InvoiceExtraction) -> ArithmeticCheck:
        """Sanity check: tax should not exceed total."""
        tax = self._to_decimal(extraction.tax_amount.value)
        total = self._to_decimal(extraction.total_amount.value)

        if tax is None or total is None:
            return ArithmeticCheck(
                check_name="tax_not_exceeds_total",
                status="skipped",
                detail="Tax or total not available",
            )

        if tax <= total:
            return ArithmeticCheck(
                check_name="tax_not_exceeds_total",
                expected=float(total),
                actual=float(tax),
                status="pass",
                detail=f"Tax {tax} ≤ Total {total} ✓",
            )
        else:
            return ArithmeticCheck(
                check_name="tax_not_exceeds_total",
                expected=float(total),
                actual=float(tax),
                status="fail",
                detail=f"Tax {tax} > Total {total} — suspicious",
            )
