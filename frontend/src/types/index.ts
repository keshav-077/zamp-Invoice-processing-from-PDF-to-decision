/** Shared API and domain types for InvoiceFlow AI */

export interface ExtractedField<T = string | number | null> {
  value: T
  confidence: number
  status: 'extracted' | 'inferred' | 'not_found' | 'uncertain'
}

export interface ExtraCharge {
  label: string
  category: string
  amount: number
  confidence: number
}

export interface LineItem {
  line_number?: number
  description: string
  quantity?: number | null
  unit_price?: number | null
  amount?: number | null
  confidence: number
}

export interface InvoiceExtraction {
  vendor_name: ExtractedField<string>
  invoice_number: ExtractedField<string>
  invoice_date: ExtractedField<string>
  due_date: ExtractedField<string>
  due_date_terms: ExtractedField<string>
  po_reference: ExtractedField<string>
  currency: ExtractedField<string>
  subtotal: ExtractedField<number>
  tax_amount: ExtractedField<number>
  total_amount: ExtractedField<number>
  line_items: LineItem[]
  extra_charges?: ExtraCharge[]
}

export interface VerificationIssue {
  field: string
  severity: 'high' | 'medium' | 'low'
  reason: string
}

export interface VerificationResult {
  verification_status: string
  overall_confidence: number
  issues: VerificationIssue[]
}

export interface ReconciliationCheck {
  check_name: string
  status: string
  detail?: string
}

export interface ReconciliationResult {
  overall_status: string
  residual_amount?: number | null
  inferred_charges?: { label: string; amount: number }[]
  checks: ReconciliationCheck[]
}

export interface ArithmeticResult {
  overall_status: string
  checks: ReconciliationCheck[]
}

export interface ScoreBreakdown {
  po_match?: number
  vendor_match?: number
  line_match?: number
  amount_match?: number
  historical_match?: number
  date_match?: number
  total?: number
}

export interface POCandidate {
  po_number: string
  vendor_name?: string
  po_status?: string
  score?: ScoreBreakdown
  evidence?: string[]
  retrieval_method?: string
  import_derived?: boolean
  structured_evidence?: Array<{ signal: string; detail?: string; status?: string }>
}

export interface MatchExplanation {
  summary?: string
  details?: string[]
  extraction_available?: string[]
  extraction_missing?: string[]
  candidates_searched?: number
  candidates_viable?: number
  matched_po_numbers?: string[]
}

export interface EvidenceProfile {
  available?: string[]
  missing?: string[]
  optional_missing?: string[]
  uncertain?: string[]
  critical_missing?: string[]
  matchable_signals?: string[]
}

export type Stage2MatchStatus =
  | 'matched'
  | 'high_confidence_match'
  | 'ambiguous_match'
  | 'partial_match'
  | 'non_po_workflow'
  | 'waiting_for_po'
  | 'suggested_po_match'
  | 'waiting_for_grn'
  | 'closed_po_review'
  | 'unmatched'
  | 'no_matching_evidence'
  | 'multiple_candidates'
  | 'po_suggestions_rejected'

export interface Stage2Result {
  match_status?: Stage2MatchStatus | string
  po_presence?: string
  matched_pos?: POCandidate[]
  suggested_candidates?: POCandidate[]
  evidence?: string[]
  flags?: string[]
  confidence_gate_action?: string
  suggestion_mode?: boolean
  vendor_master_status?: string
  match_provenance?: string
  explanation?: MatchExplanation
  evidence_profile?: EvidenceProfile
  next_stage?: string
  candidate_count?: number
}

export interface ValidationCheck {
  check_id: string
  status: string
  reason_code?: string
  severity?: string
  evidence?: string[]
  calculation?: Record<string, unknown>
}

export interface ControlRecord {
  control_id: string
  control_type: string
  reason_code: string
  state?: string
  detail?: string
}

export interface FraudSignal {
  signal_type: string
  severity?: string
  description: string
}

export interface ValidationReport {
  validation_run_id?: string
  overall_state?: string
  processing_state?: string
  reason_codes?: string[]
  checks?: Record<string, ValidationCheck>
  controls?: ControlRecord[]
  fraud_signals?: FraudSignal[]
  evidence_summary?: string[]
}

export interface RuleEvaluation {
  rule_id: string
  result: string
  detail?: string
  priority?: number
}

export interface DecisionRecord {
  decision_id?: string
  decision?: string
  decision_substate?: string
  reason_codes?: string[]
  trace?: {
    rules_evaluated?: RuleEvaluation[]
    policy?: Record<string, unknown>
    authority?: Record<string, unknown>
    routing?: Record<string, unknown>
  }
  evidence_summary?: string[]
}

export interface NarrativeEntry {
  step: number
  category: string
  text: string
  source_rule_id?: string
  icon?: string
}

export interface EvidenceGap {
  stage: number
  artifact_type?: string
  reason: string
  impact?: string
}

export interface Stage5Result {
  explanation_id?: string
  explanation_status?: string
  decision_outcome?: string
  decision_substate?: string
  narrative?: NarrativeEntry[]
  gaps?: EvidenceGap[]
  control_verifications?: {
    control_id: string
    status: string
    evidence?: string
    gap_reason?: string
  }[]
}

export interface PipelineResult {
  document_id: string
  filename: string
  status: string
  upload_timestamp?: string
  processing_time_seconds: number
  extraction: InvoiceExtraction | null
  verification: VerificationResult | null
  arithmetic: ArithmeticResult | null
  reconciliation: ReconciliationResult | null
  evidence_profile?: EvidenceProfile | null
  extraction_quality?: string
  workflow_state?: string
  decision_explanation: string[]
  stage2_status: string
  stage2_result: Stage2Result | null
  stage3_status: string
  stage3_result?: ValidationReport | null
  stage4_decision: string
  stage4_status: string
  stage4_result?: DecisionRecord | null
  stage5_result: Stage5Result | null
  stage5_status: string
  stage5_explanation_id: string
  document_quality_score?: number
}

export interface InvoiceRun extends Partial<PipelineResult> {
  document_id: string
  filename?: string
  status?: string
  upload_timestamp?: string
  processing_time_seconds?: number
  extraction_json?: InvoiceExtraction
  verification_json?: VerificationResult
  arithmetic_json?: ArithmeticResult
  reconciliation_json?: ReconciliationResult
  decision_explanation_json?: string[] | string
  stage2_result_json?: Stage2Result
  stage3_result_json?: ValidationReport
  stage4_result_json?: DecisionRecord
  stage5_result_json?: Stage5Result
}

export interface StatsResponse {
  total_invoices: number
  stage1_passed: number
  needs_human_review: number
  extraction_failed: number
  avg_processing_time: number
  auto_approval_rate: number
  status_counts: Record<string, number>
}

export interface HealthResponse {
  status: string
  available_providers: string[]
  configured_priority: string[]
}

export interface WorkItem {
  work_item_id: string
  document_id: string
  queue: string
  reason_codes?: string[]
  reason_codes_json?: string
  priority: string
  sla_due_at?: string
  status: string
}

export interface ExceptionAnalytics {
  auto_pass_rate: number
  po_suggestion_acceptance_rate: number
  residual_review_count: number
  total_processed: number
}

export interface AuditReconstruct {
  document_id: string
  integrity_status: string
  stage5_explanation?: Stage5Result | null
}
