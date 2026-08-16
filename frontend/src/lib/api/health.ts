import type { HealthResponse } from '@/types'
import { apiRequest } from './client'

export function fetchHealth() {
  return apiRequest<HealthResponse>('/health', { timeout: 3000 })
}
