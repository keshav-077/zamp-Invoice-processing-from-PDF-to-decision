import type {
  DecisionRecord,
  InvoiceExtraction,
  InvoiceRun,
  PipelineResult,
  Stage2Result,
  Stage5Result,
  ValidationReport,
} from '@/types'

export function coalesceDict<T>(value: T | null | undefined): T extends object ? T : Record<string, never> {
  return (value && typeof value === 'object' ? value : {}) as T extends object ? T : Record<string, never>
}

export function parseJsonField<T>(value: T | string | null | undefined): T | null {
  if (value == null) return null
  if (typeof value === 'string') {
    try {
      return JSON.parse(value) as T
    } catch {
      return null
    }
  }
  return value as T
}

export function num(value: unknown, defaultValue = 0): number {
  if (value == null) return defaultValue
  const n = Number(value)
  return Number.isFinite(n) ? n : defaultValue
}

export function scoreTotal(score: Record<string, unknown> | undefined): number {
  if (!score) return 0
  if (score.total != null) return num(score.total)
  return ['po_match', 'vendor_match', 'line_match', 'amount_match', 'historical_match', 'date_match']
    .reduce((sum, key) => sum + num(score[key]), 0)
}

/** Normalize DB history row into PipelineResult-like shape */
export function normalizeInvoiceRun(row: InvoiceRun): PipelineResult {
  const extraction =
    parseJsonField<InvoiceExtraction>(row.extraction) ??
    parseJsonField<InvoiceExtraction>(row.extraction_json)
  const verification =
    parseJsonField(row.verification) ?? parseJsonField(row.verification_json)
  const arithmetic =
    parseJsonField(row.arithmetic) ?? parseJsonField(row.arithmetic_json)
  const reconciliation =
    parseJsonField(row.reconciliation) ?? parseJsonField(row.reconciliation_json)
  const stage2 =
    parseJsonField<Stage2Result>(row.stage2_result) ??
    parseJsonField<Stage2Result>(row.stage2_result_json)
  const stage3 =
    parseJsonField<ValidationReport>(row.stage3_result) ??
    parseJsonField<ValidationReport>(row.stage3_result_json)
  const stage4 =
    parseJsonField<DecisionRecord>(row.stage4_result) ??
    parseJsonField<DecisionRecord>(row.stage4_result_json)
  const stage5 =
    parseJsonField<Stage5Result>(row.stage5_result) ??
    parseJsonField<Stage5Result>(row.stage5_result_json)

  let decisionExplanation = row.decision_explanation ?? []
  if (!decisionExplanation.length) {
    const parsed = parseJsonField<string[]>(row.decision_explanation_json)
    if (parsed) decisionExplanation = parsed
    else if (typeof row.decision_explanation_json === 'string') {
      decisionExplanation = [row.decision_explanation_json]
    }
  }

  return {
    document_id: row.document_id,
    filename: row.filename ?? 'Unknown',
    status: row.status ?? 'unknown',
    upload_timestamp: row.upload_timestamp,
    processing_time_seconds: num(row.processing_time_seconds),
    document_quality_score: num(row.document_quality_score, NaN) || undefined,
    extraction,
    verification,
    arithmetic,
    reconciliation,
    decision_explanation: decisionExplanation,
    stage2_status: row.stage2_status ?? '',
    stage2_result: stage2,
    stage3_status: row.stage3_status ?? stage3?.overall_state ?? '',
    stage3_result: stage3,
    stage4_decision: row.stage4_decision ?? stage4?.decision ?? '',
    stage4_status: row.stage4_status ?? stage4?.decision_substate ?? '',
    stage4_result: stage4,
    stage5_result: stage5,
    stage5_status: row.stage5_status ?? '',
    stage5_explanation_id: row.stage5_explanation_id ?? '',
  }
}
