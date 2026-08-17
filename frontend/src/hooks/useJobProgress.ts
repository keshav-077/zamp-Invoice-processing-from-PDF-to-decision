import { useEffect, useState } from 'react'
import type { RailStageStatus } from '@/components/journey/StageProgressRail'
import { fetchJobStatus } from '@/lib/api/jobs'
import { formatApiErrorMessage } from '@/lib/api/client'

const STAGE_KEYS = ['stage1', 'stage2', 'stage3', 'stage4', 'stage5'] as const

function mapStageStatuses(stageStatus: Record<string, string> | undefined): {
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
  const activeIdx = statuses.findIndex((s) => s === 'active')
  const activeStage = activeIdx >= 0 ? activeIdx + 1 : statuses.filter((s) => s === 'done').length + 1
  return { activeStage: Math.min(5, Math.max(1, activeStage)), stageStatuses: statuses }
}

export function useJobProgress(jobId: string | null, enabled: boolean) {
  const [activeStage, setActiveStage] = useState(1)
  const [stageStatuses, setStageStatuses] = useState<RailStageStatus[]>([
    'pending',
    'pending',
    'pending',
    'pending',
    'pending',
  ])
  const [documentId, setDocumentId] = useState<string | null>(null)
  const [status, setStatus] = useState<string>('queued')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!enabled || !jobId) return

    let cancelled = false
    const poll = async () => {
      try {
        const job = await fetchJobStatus(jobId)
        if (cancelled) return
        setStatus(job.status)
        setDocumentId(job.document_id || null)
        const mapped = mapStageStatuses(job.stage_status)
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
        if (!cancelled) setError(formatApiErrorMessage(e, 'Could not check job status'))
        return false
      }
    }

    const interval = setInterval(async () => {
      const cont = await poll()
      if (!cont) clearInterval(interval)
    }, 2000)
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
    isComplete: status === 'completed',
    isFailed: status === 'failed',
  }
}
