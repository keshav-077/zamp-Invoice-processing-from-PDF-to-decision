import { useEffect, useState } from 'react'
import type { RailStageStatus } from '@/components/journey/StageProgressRail'
import { fetchJobStatus } from '@/lib/api/jobs'
import { formatApiErrorMessage } from '@/lib/api/client'

const STAGE_KEYS = ['stage1', 'stage2', 'stage3', 'stage4', 'stage5'] as const
const POLL_MS = 2500
const MAX_POLL_ERRORS = 8

function mapStageStatuses(
  stageStatus: Record<string, string> | undefined,
  jobStatus: string,
): {
  activeStage: number
  stageStatuses: RailStageStatus[]
} {
  const statuses: RailStageStatus[] = STAGE_KEYS.map((key) => {
    const s = stageStatus?.[key] ?? 'pending'
    if (s === 'done') return 'done'
    if (s === 'active') return 'active'
    if (s === 'failed') return 'error'
    return 'pending'
  })

  // Optimistic UI while job is queued/processing before backend updates stages
  if (
    (jobStatus === 'queued' || jobStatus === 'processing') &&
    !statuses.some((s) => s === 'active' || s === 'done')
  ) {
    statuses[0] = 'active'
  }

  const activeIdx = statuses.findIndex((s) => s === 'active')
  const activeStage = activeIdx >= 0 ? activeIdx + 1 : statuses.filter((s) => s === 'done').length + 1
  return { activeStage: Math.min(5, Math.max(1, activeStage)), stageStatuses: statuses }
}

export function useJobProgress(jobId: string | null, enabled: boolean) {
  const [activeStage, setActiveStage] = useState(1)
  const [stageStatuses, setStageStatuses] = useState<RailStageStatus[]>([
    'active',
    'pending',
    'pending',
    'pending',
    'pending',
  ])
  const [documentId, setDocumentId] = useState<string | null>(null)
  const [status, setStatus] = useState<string>('queued')
  const [error, setError] = useState<string | null>(null)
  const [pollCount, setPollCount] = useState(0)

  useEffect(() => {
    if (!enabled || !jobId) return

    let cancelled = false
    let pollErrors = 0

    const poll = async () => {
      try {
        const job = await fetchJobStatus(jobId)
        pollErrors = 0
        if (cancelled) return false
        setPollCount((c) => c + 1)
        setStatus(job.status)
        setDocumentId(job.document_id || null)
        const mapped = mapStageStatuses(job.stage_status, job.status)
        setActiveStage(mapped.activeStage)
        setStageStatuses(mapped.stageStatuses)
        if (job.status === 'failed') {
          setError(job.error_message?.trim() || 'Processing failed')
        }
        if (job.status === 'completed' || job.status === 'failed') {
          return false
        }
        return true
      } catch (e) {
        pollErrors += 1
        if (!cancelled && pollErrors >= MAX_POLL_ERRORS) {
          setError(formatApiErrorMessage(e, 'Could not check job status'))
          return false
        }
        return true
      }
    }

    const interval = setInterval(async () => {
      const cont = await poll()
      if (!cont) clearInterval(interval)
    }, POLL_MS)
    poll()

    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [jobId, enabled])

  return {
    activeStage,
    stageStatuses,
    documentId,
    status,
    error,
    pollCount,
    isComplete: status === 'completed',
    isFailed: status === 'failed',
    isRunning: status === 'queued' || status === 'processing',
  }
}
