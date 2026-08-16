import type { ExceptionAnalytics, WorkItem } from '@/types'
import { apiRequest } from './client'

export function fetchReviews(params?: { limit?: number; queue?: string }) {
  const search = new URLSearchParams()
  search.set('limit', String(params?.limit ?? 50))
  if (params?.queue) search.set('queue', params.queue)
  return apiRequest<{ work_items: WorkItem[]; count: number }>(
    `/reviews?${search}`,
    { timeout: 5000 },
  )
}

export function submitReviewAction(
  documentId: string,
  body: {
    action_type: string
    actor_id: string
    detail: string
    outcome: string
  },
) {
  return apiRequest(`/reviews/${documentId}/actions`, {
    method: 'POST',
    body,
    timeout: 15000,
  })
}

export function fetchExceptionAnalytics() {
  return apiRequest<ExceptionAnalytics>('/analytics/exceptions', { timeout: 5000 })
}
