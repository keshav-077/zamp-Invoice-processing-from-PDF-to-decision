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
  if (typeof detail === 'string') {
    const trimmed = detail.trim()
    return trimmed || fallback || 'Request failed'
  }
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((item) => {
        if (typeof item === 'string') return item
        if (item && typeof item === 'object') {
          const row = item as { msg?: string; message?: string; loc?: unknown[] }
          const loc = Array.isArray(row.loc) ? row.loc.join('.') : ''
          const msg = row.msg ?? row.message
          if (msg && loc) return `${loc}: ${msg}`
          if (msg) return msg
        }
        return null
      })
      .filter(Boolean)
    if (msgs.length > 0) return msgs.slice(0, 3).join('; ')
  }
  if (detail && typeof detail === 'object') {
    const obj = detail as Record<string, unknown>
    const errors = obj.errors
    if (Array.isArray(errors) && errors.length > 0) {
      const head = errors.slice(0, 3).map(String).join('; ')
      const more = errors.length > 3 ? ` (+${errors.length - 3} more)` : ''
      return `Import failed: ${head}${more}`
    }
    if (typeof obj.message === 'string' && obj.message.trim()) return obj.message.trim()
    if (typeof obj.error === 'string' && obj.error.trim()) return obj.error.trim()
    if (typeof obj.error_message === 'string' && obj.error_message.trim()) {
      return obj.error_message.trim()
    }
  }
  const fb = (fallback || '').trim()
  if (fb && fb.toLowerCase() !== 'request failed') return fb
  return 'Server error — unexpected response'
}

/** User-facing message for any API or network failure — never returns an empty string. */
export function formatApiErrorMessage(err: unknown, fallback = 'Something went wrong'): string {
  const normalize = (text: string) => text.replace(/\s+/g, ' ').trim()

  if (err instanceof ApiError) {
    const msg = normalize(err.detail || '')
    if (msg) return msg
    if (err.status === 408) {
      return 'Request timed out — try again or use a smaller file'
    }
    if (err.status === 429) return 'Rate limit exceeded — wait a minute and try again'
    if (err.status === 501) return 'This feature is not configured on the server'
    if (err.status === 0 || err.status === 502 || err.status === 503 || err.status === 504) {
      return 'Could not reach the API — check that the backend is running'
    }
    if (err.status > 0) return `${fallback} (HTTP ${err.status})`
    return 'Could not reach the API — check that the backend is running'
  }
  if (err instanceof Error) {
    const msg = normalize(err.message || '')
    if (msg === 'Failed to fetch') {
      return 'Could not reach the API — ensure the backend is running on port 8000'
    }
    if (msg) return msg
  }
  if (typeof err === 'string' && err.trim()) return err.trim()
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
      const message =
        formatApiDetail(payload ?? detail, detail).trim() ||
        (response.status > 0
          ? `Server error (HTTP ${response.status})`
          : 'Server error — no response from API')
      throw new ApiError(response.status, message, payload)
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
    throw new ApiError(0, formatApiErrorMessage(err, 'Network error'))
  } finally {
    clearTimeout(timer)
  }
}

export function getOriginalFileUrl(documentId: string): string {
  return `${API_BASE}/invoices/${documentId}/original`
}

export { API_BASE, UPLOAD_TIMEOUT }
