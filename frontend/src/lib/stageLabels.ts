/** Human-readable labels for machine codes */

export const REASON_CODE_LABELS: Record<string, { title: string; description: string }> = {
  DUPLICATE_CONFIRMED: {
    title: 'Duplicate invoice',
    description: 'This invoice number was already processed in the system.',
  },
  TAX_VARIANCE: {
    title: 'Tax amount mismatch',
    description: 'Extracted tax does not match PO or expected rate.',
  },
  AMOUNT_VARIANCE_DETECTED: {
    title: 'Amount variance',
    description: 'Invoice total differs from PO or expected amount.',
  },
  VENDOR_MISMATCH: {
    title: 'Vendor mismatch',
    description: 'Invoice vendor does not match the PO vendor.',
  },
  PO_NOT_FOUND: {
    title: 'PO not found',
    description: 'Referenced PO number is not in the database.',
  },
}

export const SUBSTATE_LABELS: Record<string, string> = {
  AUTO_APPROVED: 'Invoice auto-approved — all controls passed within policy limits.',
  APPROVAL_REQUIRED: 'Manual approval required before payment.',
  STANDARD_REVIEW: 'Routed to AP exception team for standard review.',
  HIGH_PRIORITY_REVIEW: 'Requires senior finance review due to validation flags.',
  FRAUD_REVIEW: 'Flagged for fraud and security review.',
  VENDOR_SECURITY_REVIEW: 'Vendor bank or identity changes require security review.',
  POLICY_EXCEPTION_REVIEW: 'Policy exception review required.',
  TERMINAL_REJECT: 'Invoice rejected — terminal validation failure cannot be overridden.',
  WAITING_FOR_GRN: 'Processing paused — awaiting goods receipt.',
  WAITING_FOR_REQUIRED_DATA: 'Processing paused — missing required data.',
}

export const STAGE_TITLES: Record<number, string> = {
  1: 'Extract & Verify',
  2: 'PO Matching',
  3: 'Validation',
  4: 'Business Decision',
  5: 'Explanation',
}

export function labelReasonCode(code: string): { title: string; description: string } {
  return (
    REASON_CODE_LABELS[code] ?? {
      title: code.replace(/_/g, ' '),
      description: 'See validation details for more information.',
    }
  )
}

export function labelSubstate(substate: string): string {
  return SUBSTATE_LABELS[substate] ?? substate.replace(/_/g, ' ').toLowerCase()
}
