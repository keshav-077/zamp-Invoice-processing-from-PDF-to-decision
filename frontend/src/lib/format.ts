import { num } from './normalize'

export function formatCurrency(value: unknown, currency = 'USD'): string {
  const n = num(value)
  if (currency === 'USD') return `$${n.toFixed(2)}`
  return `${n.toFixed(2)} ${currency}`
}

export function formatTimestamp(ts?: string): string {
  if (!ts) return '—'
  return ts.slice(0, 19).replace('T', ' ')
}

export function formatDuration(seconds?: number): string {
  if (seconds == null) return '—'
  return `${num(seconds).toFixed(1)}s`
}

export function statusLabel(status: string): string {
  return status.replace(/_/g, ' ').toUpperCase()
}

export const STAGE1_BADGE: Record<string, { label: string; variant: 'success' | 'warning' | 'danger' }> = {
  stage1_passed: { label: 'STAGE 1 PASSED', variant: 'success' },
  needs_human_review: { label: 'NEEDS HUMAN REVIEW', variant: 'warning' },
  extraction_failed: { label: 'EXTRACTION FAILED', variant: 'danger' },
}

export const STAGE2_BADGE: Record<string, string> = {
  matched: 'PO MATCHED',
  high_confidence_match: 'PO MATCHED',
  ambiguous_match: 'AMBIGUOUS PO MATCH',
  partial_match: 'PARTIAL PO MATCH',
  non_po_workflow: 'NON-PO WORKFLOW',
  waiting_for_po: 'PO NOT IN DATABASE',
  suggested_po_match: 'SUGGESTED PO MATCH',
  po_suggestions_rejected: 'PO REJECTED',
  waiting_for_grn: 'WAITING FOR GRN',
  closed_po_review: 'CLOSED PO REVIEW',
  unmatched: 'PO UNMATCHED',
  no_matching_evidence: 'INSUFFICIENT EXTRACTION',
  multiple_candidates: 'MULTIPLE PO CANDIDATES',
}

export const PIPELINE_STEPS = [
  'Input Validation & Preprocessing',
  'Page Classification',
  'Primary Extraction (LLM #1)',
  'Independent Verification (LLM #2)',
  'Reconciliation',
  'Stage 1 Routing Decision',
  'Stage 2 PO Matching',
  'Stage 3 Validation',
  'Stage 4 Business Decision',
]
