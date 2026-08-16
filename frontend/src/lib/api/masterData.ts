import { apiRequest, UPLOAD_TIMEOUT } from './client'

export interface ColumnMapping {
  source_column: string
  canonical_field: string | null
  confidence: number
  status: 'auto' | 'review' | 'metadata' | 'profile'
  reason: string
}

export interface SheetProfile {
  sheet: string
  entity: string
  row_count: number
  columns: string[]
  column_mappings?: ColumnMapping[]
  sample_rows?: Record<string, unknown>[]
}

export interface ActivationBucket {
  ready: number
  skipped: number
  review: number
  blocked: number
}

export type ClassificationSummary = Record<string, ActivationBucket>

export interface RowIssue {
  row_index: number
  sheet: string
  record_type: string
  status: string
  severity: string
  message: string
}

export interface SourceRecord {
  source_record_id: string
  record_type: string
  vendor_name?: string
  invoice_number?: string
  invoice_total?: number
  po_reference?: string
  po_reference_status?: string
}

export interface MasterDataPreview {
  valid: boolean
  partial_success?: boolean
  errors: string[]
  warnings: string[]
  summary: Record<string, number>
  classification_summary?: ClassificationSummary
  row_issues?: RowIssue[]
  preview: {
    profile?: { sheets: SheetProfile[]; source_fingerprint?: string }
    batch_id?: string
    review_needed?: boolean
    unknown_columns?: Array<{ sheet: string; column: string; entity?: string }>
    vendors?: unknown[]
    purchase_orders?: unknown[]
    po_lines?: unknown[]
    source_records?: SourceRecord[]
  }
  committed?: boolean
  import_id?: string
  batch_id?: string
  file_checksum?: string
  review_needed?: boolean
}

export async function previewMasterData(file: File, companyId = 'DEFAULT'): Promise<MasterDataPreview> {
  const form = new FormData()
  form.append('file', file)
  return apiRequest<MasterDataPreview>(`/master-data/preview?company_id=${companyId}`, {
    method: 'POST',
    formData: form,
    timeout: UPLOAD_TIMEOUT,
  })
}

export async function importMasterData(file: File, companyId = 'DEFAULT'): Promise<MasterDataPreview> {
  const form = new FormData()
  form.append('file', file)
  return apiRequest<MasterDataPreview>(`/master-data/import?company_id=${companyId}`, {
    method: 'POST',
    formData: form,
    timeout: UPLOAD_TIMEOUT,
  })
}

export async function confirmMasterDataImport(
  file: File,
  sheets: SheetProfile[],
  companyId = 'DEFAULT',
): Promise<MasterDataPreview> {
  const form = new FormData()
  form.append('file', file)
  form.append('mappings', JSON.stringify({ sheets }))
  return apiRequest<MasterDataPreview>(`/master-data/import/confirm?company_id=${companyId}`, {
    method: 'POST',
    formData: form,
    timeout: UPLOAD_TIMEOUT,
  })
}

export async function listMasterDataImports(companyId = 'DEFAULT') {
  return apiRequest<{ imports: unknown[]; count: number }>(
    `/master-data/imports?company_id=${companyId}`,
  )
}

export async function listSourceRecords(companyId = 'DEFAULT', limit = 100) {
  return apiRequest<{ records: SourceRecord[]; count: number }>(
    `/master-data/source-records?company_id=${companyId}&limit=${limit}`,
  )
}
