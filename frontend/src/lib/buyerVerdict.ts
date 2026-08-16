import type { PipelineResult } from '@/types'

export type BuyerVerdict = 'pay' | 'do_not_pay' | 'needs_review' | 'pending'

export interface BuyerVerdictDetails {
  verdict: BuyerVerdict
  headline: string
  reason: string
  detail?: string
}

const BLOCK_REASON_MESSAGES: Record<string, string> = {
  DUPLICATE_CONFIRMED:
    'Do not pay — this invoice was already processed and approved for payment (duplicate).',
  VENDOR_BLACKLISTED: 'Do not pay — vendor is blacklisted or suspended.',
}

const HOLD_REASON_MESSAGES: Record<string, string> = {
  TAX_VARIANCE: 'Tax on the invoice does not match expected policy — AP review required before payment.',
  PRICE_VARIANCE_EXCEEDED: 'Price variance exceeds tolerance — review before payment.',
  BUDGET_EXCEEDED: 'Invoice exceeds PO budget tolerance — review before payment.',
}

function primaryReasonCodes(result: PipelineResult): string[] {
  const stage3 = result.stage3_result
  if (stage3?.controls?.length) {
    const block = stage3.controls.find((c) => c.control_type === 'BLOCK')
    if (block?.reason_code) return [block.reason_code]
  }
  return stage3?.reason_codes ?? []
}

function rejectReason(result: PipelineResult): { reason: string; detail?: string } {
  const codes = primaryReasonCodes(result)
  const top = codes[0]
  if (top && BLOCK_REASON_MESSAGES[top]) {
    const control = result.stage3_result?.controls?.find((c) => c.reason_code === top)
    return {
      reason: BLOCK_REASON_MESSAGES[top],
      detail: control?.detail,
    }
  }
  if (codes.includes('DUPLICATE_CONFIRMED')) {
    return {
      reason: BLOCK_REASON_MESSAGES.DUPLICATE_CONFIRMED,
      detail: result.stage3_result?.controls?.[0]?.detail,
    }
  }
  return {
    reason: 'This invoice was rejected by policy controls.',
    detail: codes.length ? `Reason codes: ${codes.join(', ')}` : undefined,
  }
}

export function mapBuyerVerdict(result: PipelineResult): BuyerVerdictDetails {
  const decision = result.stage4_decision || result.stage4_result?.decision || ''
  const stage3 = result.stage3_status || ''
  const stage2 = result.stage2_status || ''
  const substate = result.stage4_status || result.stage4_result?.decision_substate || ''

  if (decision === 'TERMINAL_REJECT' || decision === 'REJECT') {
    const { reason, detail } = rejectReason(result)
    return {
      verdict: 'do_not_pay',
      headline: 'Do not pay',
      reason,
      detail,
    }
  }

  if (substate === 'AUTO_APPROVED' || decision === 'APPROVE') {
    return {
      verdict: 'pay',
      headline: 'Pay',
      reason: 'Invoice matched PO, passed validation, and is within auto-approve limits.',
    }
  }

  if (decision === 'REVIEW_REQUIRED' || decision === 'APPROVAL_REQUIRED') {
    return {
      verdict: decision === 'APPROVAL_REQUIRED' ? 'pay' : 'needs_review',
      headline: decision === 'APPROVAL_REQUIRED' ? 'Pay — approval required' : 'Needs review',
      reason:
        decision === 'APPROVAL_REQUIRED'
          ? 'Invoice validated; route for approval before payment release.'
          : 'Additional review required before payment.',
    }
  }

  if (stage3 === 'HOLD' && decision !== 'AUTO_APPROVED') {
    const codes = primaryReasonCodes(result)
    const top = codes.find((c) => HOLD_REASON_MESSAGES[c])
    return {
      verdict: 'needs_review',
      headline: 'Needs review',
      reason: top
        ? HOLD_REASON_MESSAGES[top]
        : 'Validation found issues that require AP review before payment.',
      detail: result.stage3_result?.controls?.[0]?.detail,
    }
  }

  if (
    stage2 === 'ambiguous_match' ||
    stage2 === 'multiple_candidates' ||
    stage2 === 'no_matching_evidence' ||
    stage2 === 'waiting_for_po' ||
    stage2 === 'suggested_po_match' ||
    stage2 === 'partial_match' ||
    stage2 === 'unmatched' ||
    stage2 === 'non_po_workflow'
  ) {
    return {
      verdict: 'needs_review',
      headline: 'Needs review',
      reason:
        stage2 === 'no_matching_evidence'
          ? 'Extraction lacked enough data for PO matching.'
          : stage2 === 'suggested_po_match' || stage2 === 'waiting_for_po'
            ? 'PO match needs human confirmation.'
            : 'PO match or routing needs human confirmation.',
    }
  }

  if (result.extraction_quality === 'extraction_weak') {
    return {
      verdict: 'needs_review',
      headline: 'Needs review',
      reason: 'Extraction quality is too weak for automated processing.',
    }
  }

  return {
    verdict: 'pending',
    headline: 'Processing',
    reason: 'Pipeline has not reached a final decision yet.',
  }
}
