/**
 * API base URL — defaults to same-origin /api in production builds (Vercel).
 * Override with VITE_API_BASE_URL for local dev or split hosting.
 */
function resolveApiBase(): string {
  const configured = import.meta.env.VITE_API_BASE_URL
  if (configured && configured.trim()) {
    return configured.replace(/\/$/, '')
  }
  if (import.meta.env.PROD) {
    return '/api'
  }
  return 'http://localhost:8000/api'
}

const API_BASE = resolveApiBase()
const UPLOAD_TIMEOUT = Number(import.meta.env.VITE_UPLOAD_TIMEOUT_MS ?? 300000)

function formatApiDetail(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object') {
    const obj = detail as Record<string, unknown>
    const errors = obj.errors
    if (Array.isArray(errors) && errors.length > 0) {
      const head = errors.slice(0, 3).map(String).join('; ')
      const more = errors.length > 3 ? ` (+${errors.length - 3} more)` : ''
      return `Import failed: ${head}${more}`
    }
    if (typeof obj.message === 'string') return obj.message
  }
  return fallback
}

export class ApiError extends Error {
  status: number
  detail: string
  payload?: unknown

  constructor(status: number, detail: string, payload?: unknown) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.payload = payload
  }
}

interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown
  timeout?: number
  formData?: FormData
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, timeout = 30000, formData, headers, ...rest } = options
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeout)

  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...rest,
      signal: controller.signal,
      headers: formData
        ? headers
        : {
            'Content-Type': 'application/json',
            ...headers,
          },
      body: formData ?? (body != null ? JSON.stringify(body) : undefined),
    })

    if (!response.ok) {
      let detail = response.statusText
      let payload: unknown
      try {
        const err = (await response.json()) as { detail?: unknown }
        payload = err.detail
        detail = formatApiDetail(err.detail, detail)
      } catch {
        /* ignore */
      }
      throw new ApiError(response.status, detail, payload)
    }

    if (response.status === 204) return undefined as T

    const contentType = response.headers.get('content-type') ?? ''
    if (contentType.includes('application/json')) {
      return (await response.json()) as T
    }

    return response as unknown as T
  } catch (err) {
    if (err instanceof ApiError) throw err
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ApiError(408, 'Request timed out')
    }
    throw new ApiError(0, err instanceof Error ? err.message : 'Network error')
  } finally {
    clearTimeout(timer)
  }
}

export function getOriginalFileUrl(documentId: string): string {
  return `${API_BASE}/invoices/${documentId}/original`
}

export { API_BASE, UPLOAD_TIMEOUT }
