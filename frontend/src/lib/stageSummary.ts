import type { PipelineResult } from '@/types'
import { coalesceDict, num, scoreTotal } from '@/lib/normalize'
import { labelSubstate } from '@/lib/stageLabels'

export type StageOutcome = 'pass' | 'warn' | 'fail' | 'skipped'

export interface StageSummary {
  outcome: StageOutcome
  badge: string
  summary: string
}

const STAGE2_PASS = new Set(['matched', 'high_confidence_match'])
const STAGE2_WARN = new Set([
  'ambiguous_match',
  'partial_match',
  'non_po_workflow',
  'waiting_for_po',
  'suggested_po_match',
  'waiting_for_grn',
  'closed_po_review',
  'no_matching_evidence',
  'multiple_candidates',
  'unmatched',
])

export function splitDecisionExplanation(lines: string[]) {
  const byStage: Record<number, string[]> = { 1: [], 2: [], 3: [], 4: [], 5: [] }
  for (const line of lines) {
    const lower = line.toLowerCase()
    if (lower.includes('stage 2') || lower.includes('po match') || lower.includes('po ')) {
      byStage[2].push(line)
    } else if (lower.includes('stage 3') || lower.includes('validation') || lower.includes('blocked') || lower.includes('hold')) {
      byStage[3].push(line)
    } else if (lower.includes('stage 4') || lower.includes('reject') || lower.includes('review_required') || lower.includes('approve')) {
      byStage[4].push(line)
    } else if (lower.includes('stage 5') || lower.includes('explanation')) {
      byStage[5].push(line)
    } else {
      byStage[1].push(line)
    }
  }
  return byStage
}

export function getStage1Summary(result: PipelineResult): StageSummary {
  const status = result.status
  const quality = result.extraction_quality
  if (status === 'extraction_failed' || quality === 'extraction_failed') {
    return { outcome: 'fail', badge: 'EXTRACTION FAILED', summary: 'Could not extract invoice data reliably.' }
  }
  if (quality === 'extraction_weak') {
    return {
      outcome: 'warn',
      badge: 'LIMITED EVIDENCE',
      summary: 'Extraction lacks matchable signals for PO matching.',
    }
  }
  if (status === 'needs_human_review') {
    return {
      outcome: 'warn',
      badge: 'NEEDS REVIEW',
      summary: 'Approval-critical fields or verification checks require human review.',
    }
  }
  const partialNote =
    quality === 'extraction_partial'
      ? ' Optional fields (e.g. PO reference) may be missing — matching can still proceed.'
      : ''
  return {
    outcome: 'pass',
    badge: 'STAGE 1 PASSED',
    summary: `Fields extracted, verified, and totals reconciled.${partialNote}`,
  }
}

export function getStage2Summary(result: PipelineResult): StageSummary {
  const status = result.stage2_status || result.stage2_result?.match_status || ''
  if (!status) {
    return { outcome: 'skipped', badge: 'NOT RUN', summary: 'PO matching did not run for this invoice.' }
  }
  if (STAGE2_PASS.has(status)) {
    return { outcome: 'pass', badge: 'PO MATCHED', summary: 'Purchase order matched with high confidence.' }
  }
  if (STAGE2_WARN.has(status)) {
    const candidates =
      result.stage2_result?.suggested_candidates?.length ??
      result.stage2_result?.matched_pos?.length ??
      0
    return {
      outcome: 'warn',
      badge: status.replace(/_/g, ' ').toUpperCase(),
      summary:
        status === 'no_matching_evidence'
          ? 'Extraction could not provide enough information for PO matching.'
          : status === 'ambiguous_match' || status === 'multiple_candidates'
          ? `Multiple PO candidates found (${candidates}) — human confirmation needed.`
          : status === 'non_po_workflow'
            ? 'No PO on invoice — routed to non-PO workflow.'
            : status === 'suggested_po_match'
              ? `Suggested PO match available (${candidates} candidate(s)) — confirm to proceed.`
              : status === 'waiting_for_po'
                ? 'PO on invoice not found in master — confirm or import PO data.'
                : 'PO matching needs review or additional data.',
    }
  }
  return { outcome: 'fail', badge: 'UNMATCHED', summary: 'Could not match invoice to a purchase order.' }
}

export function getStage3Summary(result: PipelineResult): StageSummary {
  const state = result.stage3_status || result.stage3_result?.overall_state || ''
  if (!state) {
    return { outcome: 'skipped', badge: 'NOT RUN', summary: 'Validation did not run.' }
  }
  if (state === 'VALIDATED') {
    return { outcome: 'pass', badge: 'VALIDATED', summary: 'All validation checks passed.' }
  }
  if (state === 'REVIEW_REQUIRED' || state === 'HOLD') {
    return { outcome: 'warn', badge: state, summary: 'Validation flags require review before payment.' }
  }
  if (state === 'BLOCKED') {
    return { outcome: 'fail', badge: 'BLOCKED', summary: 'Hard validation controls block this invoice.' }
  }
  return { outcome: 'warn', badge: state, summary: 'Validation incomplete or requires attention.' }
}

export function getStage4Summary(result: PipelineResult): StageSummary {
  const decision = result.stage4_decision
  if (!decision) {
    return { outcome: 'skipped', badge: 'NOT RUN', summary: 'Business decision did not run.' }
  }
  if (decision === 'APPROVE') {
    return {
      outcome: 'pass',
      badge: 'APPROVE',
      summary: labelSubstate(result.stage4_status) || 'Approved for payment processing.',
    }
  }
  if (decision === 'REVIEW_REQUIRED') {
    return {
      outcome: 'warn',
      badge: 'REVIEW REQUIRED',
      summary: labelSubstate(result.stage4_status) || 'Manual review required before payment.',
    }
  }
  if (decision === 'REJECT') {
    return {
      outcome: 'fail',
      badge: 'REJECT',
      summary: labelSubstate(result.stage4_status) || 'Invoice rejected and will not be paid.',
    }
  }
  return { outcome: 'warn', badge: decision, summary: 'Waiting for validation or required data.' }
}

export function getStage5Summary(result: PipelineResult): StageSummary {
  const status = result.stage5_status || result.stage5_result?.explanation_status || ''
  if (!status) {
    return { outcome: 'skipped', badge: 'NOT RUN', summary: 'Explanation was not generated.' }
  }
  if (status === 'COMPLETE') {
    return { outcome: 'pass', badge: 'COMPLETE', summary: 'Full audit explanation generated for this decision.' }
  }
  if (status === 'stage5_error') {
    return {
      outcome: 'warn',
      badge: 'ERROR',
      summary: 'Explanation engine failed — check narrative fallback or re-upload the invoice.',
    }
  }
  return {
    outcome: 'warn',
    badge: status === 'INCOMPLETE' ? 'INCOMPLETE' : status.toUpperCase(),
    summary: 'Explanation generated with partial evidence — review the step-by-step narrative below.',
  }
}

export function getStageSummary(result: PipelineResult, stage: number): StageSummary {
  switch (stage) {
    case 1:
      return getStage1Summary(result)
    case 2:
      return getStage2Summary(result)
    case 3:
      return getStage3Summary(result)
    case 4:
      return getStage4Summary(result)
    case 5:
      return getStage5Summary(result)
    default:
      return { outcome: 'skipped', badge: '—', summary: '' }
  }
}

export function getStage2TopScore(result: PipelineResult): number {
  const s2 = coalesceDict(result.stage2_result)
  const candidates = s2.suggested_candidates ?? s2.matched_pos ?? []
  if (!candidates.length) return 0
  return scoreTotal(candidates[0]?.score as Record<string, unknown>)
}

export function avgFieldConfidence(result: PipelineResult): number {
  const ext = result.extraction
  if (!ext) return 0
  const fields = [
    ext.vendor_name,
    ext.invoice_number,
    ext.invoice_date,
    ext.total_amount,
    ext.subtotal,
    ext.tax_amount,
  ]
  const vals = fields.map((f) => num(f?.confidence))
  return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0
}
