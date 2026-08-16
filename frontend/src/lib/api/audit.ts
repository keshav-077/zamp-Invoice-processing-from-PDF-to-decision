import type { AuditReconstruct } from '@/types'
import { apiRequest } from './client'

export function fetchAuditReconstruct(documentId: string) {
  return apiRequest<AuditReconstruct>(`/audit/${documentId}/reconstruct`, { timeout: 5000 })
}

export function fetchExplanationNarrative(documentId: string) {
  return apiRequest<{ narrative: unknown[]; explanation_status: string }>(
    `/explanation/${documentId}/narrative`,
    { timeout: 5000 },
  )
}

export function fetchDecisionTrace(documentId: string) {
  return apiRequest(`/decision/${documentId}/trace`, { timeout: 5000 })
}
