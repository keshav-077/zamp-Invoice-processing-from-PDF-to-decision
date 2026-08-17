import { apiRequest, UPLOAD_TIMEOUT } from './client'

export interface JobStatus {
  job_id: string
  status: string
  document_id?: string
  stage_status: Record<string, string>
  error_message?: string
  filename?: string
}

export function fetchJobStatus(jobId: string) {
  return apiRequest<JobStatus>(`/jobs/${jobId}`, { timeout: 120000 })
}

export function uploadInvoiceAsync(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return apiRequest<{ job_id: string; status: string; filename: string }>('/upload/async', {
    method: 'POST',
    formData,
    timeout: UPLOAD_TIMEOUT,
  })
}
