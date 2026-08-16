"""
InvoiceFlow AI — Stage 3: Fraud & Anomaly Signal Generator

Generates signals — does NOT adjudicate fraud.
A signal can contribute to HOLD/BLOCK via control policy,
but Stage 3 preserves the distinction between observed risk
and final fraud determination.

Signals:
  1. Round-number detection
  2. Threshold shaving (just below approval limits)
  3. Invoice sequence anomaly
  4. New vendor + high amount
"""

import logging
import math

from app.models.validation import ValidationCheck, FraudSignal
from app.pipeline.stage3.validation_context import ValidationContext

logger = logging.getLogger(__name__)

RULE_ID = "FRAUD_SIGNALS"
RULE_VERSION = "FRAUD-2026.08.1"


def detect_fraud_signals(ctx: ValidationContext) -> tuple[ValidationCheck, list[FraudSignal]]:
    """
    Generate fraud/anomaly signals with evidence.

    Returns:
        (ValidationCheck, list of FraudSignals)
    """
    signals: list[FraudSignal] = []
    findings = []

    # --- 1. Round Number Detection ---
    if ctx.total_amount is not None:
        if _is_suspiciously_round(ctx.total_amount):
            signals.append(FraudSignal(
                signal_type="ROUND_NUMBER",
                severity="LOW",
                description=f"Invoice total ${ctx.total_amount:,.2f} is a suspiciously round number",
                evidence={"amount": ctx.total_amount, "check": "round_number"},
            ))
            findings.append(
                f"Signal: round-number invoice total ${ctx.total_amount:,.2f}"
            )

    # --- 2. Threshold Shaving ---
    if ctx.total_amount is not None:
        shaving_result = _check_threshold_shaving(
            ctx.total_amount, ctx.approval_thresholds
        )
        if shaving_result:
            threshold, distance = shaving_result
            signals.append(FraudSignal(
                signal_type="THRESHOLD_SHAVING",
                severity="MEDIUM",
                description=(
                    f"Invoice ${ctx.total_amount:,.2f} is ${distance:,.2f} "
                    f"below approval threshold ${threshold:,.2f}"
                ),
                evidence={
                    "amount": ctx.total_amount,
                    "threshold": threshold,
                    "distance_below": distance,
                },
            ))
            findings.append(
                f"Signal: amount ${ctx.total_amount:,.2f} is ${distance:,.2f} "
                f"below ${threshold:,.2f} approval threshold"
            )

    # --- 3. Invoice Sequence Anomaly ---
    if ctx.invoice_number:
        seq_signal = _check_sequence_anomaly(ctx.invoice_number)
        if seq_signal:
            signals.append(seq_signal)
            findings.append(f"Signal: {seq_signal.description}")

    # --- 4. First Invoice + High Amount ---
    # In production, check vendor creation date vs invoice amount percentile
    # For MVP, flag if vendor is new (V007, V008 pattern) and amount > $20K
    if ctx.total_amount is not None and ctx.total_amount > 20000:
        if ctx.matched_vendor_id and ctx.matched_vendor_id in ("V007", "V008"):
            signals.append(FraudSignal(
                signal_type="NEW_VENDOR_HIGH_AMOUNT",
                severity="MEDIUM",
                description=(
                    f"First/early invoice from vendor {ctx.matched_vendor_id} "
                    f"with high amount ${ctx.total_amount:,.2f}"
                ),
                evidence={
                    "vendor_id": ctx.matched_vendor_id,
                    "amount": ctx.total_amount,
                },
            ))
            findings.append(
                f"Signal: new vendor {ctx.matched_vendor_id} + "
                f"high amount ${ctx.total_amount:,.2f}"
            )

    # --- Build check result ---
    if not findings:
        findings.append("No fraud/anomaly signals detected")

    has_high = any(s.severity in ("HIGH", "CRITICAL") for s in signals)
    has_medium = any(s.severity == "MEDIUM" for s in signals)

    if has_high:
        status = "FLAG"
        reason = "FRAUD_SIGNALS_HIGH"
        severity = "HIGH"
    elif has_medium:
        status = "FLAG"
        reason = "FRAUD_SIGNALS_MEDIUM"
        severity = "MEDIUM"
    elif signals:
        status = "PASS"
        reason = "FRAUD_SIGNALS_LOW"
        severity = "LOW"
    else:
        status = "PASS"
        reason = ""
        severity = "LOW"

    check = ValidationCheck(
        check_id="fraud_signals",
        status=status,
        reason_code=reason,
        severity=severity,
        rule_id=RULE_ID,
        rule_version=RULE_VERSION,
        inputs={"total_amount": ctx.total_amount, "vendor_id": ctx.matched_vendor_id},
        calculation={"signals_count": len(signals)},
        evidence=findings,
    )
    return check, signals


def _is_suspiciously_round(amount: float) -> bool:
    """Check if amount is suspiciously round (exact thousands, no cents)."""
    if amount <= 0:
        return False
    # Check if it's an exact multiple of 1000 with no cents
    if amount >= 1000 and amount % 1000 == 0:
        return True
    # Check if it's an exact multiple of 500 with no cents above $5K
    if amount >= 5000 and amount % 500 == 0:
        return True
    return False


def _check_threshold_shaving(
    amount: float, thresholds: list[float], proximity_pct: float = 0.03
) -> tuple[float, float] | None:
    """
    Check if amount is just below an approval threshold.

    Returns (threshold, distance_below) or None.
    """
    for threshold in thresholds:
        distance = threshold - amount
        if 0 < distance <= threshold * proximity_pct:
            return threshold, distance
    return None


def _check_sequence_anomaly(invoice_number: str) -> FraudSignal | None:
    """
    Check for invoice numbering anomalies.
    For MVP: flag unusual patterns like very short numbers or non-standard formats.
    """
    # Very basic heuristic — in production, compare against vendor's historical pattern
    cleaned = invoice_number.strip()
    if len(cleaned) < 3:
        return FraudSignal(
            signal_type="SEQUENCE_ANOMALY",
            severity="LOW",
            description=f"Unusually short invoice number: '{cleaned}'",
            evidence={"invoice_number": cleaned, "length": len(cleaned)},
        )
    return None
