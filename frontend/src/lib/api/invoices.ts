import type { PipelineResult, StatsResponse } from '@/types'
import { apiRequest, UPLOAD_TIMEOUT } from './client'

export function uploadInvoice(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return apiRequest<PipelineResult>('/upload', {
    method: 'POST',
    formData,
    timeout: UPLOAD_TIMEOUT,
  })
}

export function fetchStats() {
  return apiRequest<StatsResponse>('/stats', { timeout: 5000 })
}

export function fetchInvoices(params?: { status?: string; limit?: number; offset?: number }) {
  const search = new URLSearchParams()
  if (params?.status) search.set('status', params.status)
  search.set('limit', String(params?.limit ?? 50))
  if (params?.offset) search.set('offset', String(params.offset))
  const qs = search.toString()
  return apiRequest<{ invoices: Record<string, unknown>[]; count: number }>(
    `/invoices?${qs}`,
    { timeout: 5000 },
  )
}

export function fetchInvoice(documentId: string) {
  return apiRequest<Record<string, unknown>>(`/invoices/${documentId}`, { timeout: 5000 })
}

export function confirmPo(
  documentId: string,
  body: { po_number: string; confirmed_by: string; notes?: string },
) {
  return apiRequest(`/invoices/${documentId}/confirm-po`, { method: 'POST', body, timeout: 30000 })
}

export function rejectPoSuggestions(
  documentId: string,
  body: { rejected_by: string; notes?: string },
) {
  return apiRequest(`/invoices/${documentId}/reject-po-suggestions`, {
    method: 'POST',
    body,
    timeout: 15000,
  })
}

export function fetchPoSuggestions(documentId: string) {
  return apiRequest(`/invoices/${documentId}/po-suggestions`, { timeout: 5000 })
}
