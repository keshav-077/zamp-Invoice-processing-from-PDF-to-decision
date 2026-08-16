import { useEffect, useState } from 'react'
import type { RailStageStatus } from '@/components/journey/StageProgressRail'

const STAGE_INTERVAL_MS = 10000

export function useAnimatedPipelineProgress(isProcessing: boolean, isSuccess: boolean, isError: boolean) {
  const [activeStage, setActiveStage] = useState(1)
  const [stageStatuses, setStageStatuses] = useState<RailStageStatus[]>([
    'pending',
    'pending',
    'pending',
    'pending',
    'pending',
  ])

  useEffect(() => {
    if (!isProcessing && !isSuccess && !isError) {
      setActiveStage(1)
      setStageStatuses(['pending', 'pending', 'pending', 'pending', 'pending'])
      return
    }

    if (isProcessing) {
      setStageStatuses((prev) => {
        const next = [...prev] as RailStageStatus[]
        next[activeStage - 1] = 'active'
        for (let i = 0; i < activeStage - 1; i++) next[i] = 'done'
        return next
      })
    }
  }, [isProcessing, activeStage])

  useEffect(() => {
    if (!isProcessing) return
    const timer = setInterval(() => {
      setActiveStage((s) => {
        if (s >= 4) return 4
        return s + 1
      })
    }, STAGE_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [isProcessing])

  useEffect(() => {
    if (isSuccess) {
      setActiveStage(5)
      setStageStatuses(['done', 'done', 'done', 'done', 'done'])
    }
  }, [isSuccess])

  useEffect(() => {
    if (isError) {
      setStageStatuses((prev) => {
        const next = [...prev] as RailStageStatus[]
        next[activeStage - 1] = 'error'
        return next
      })
    }
  }, [isError, activeStage])

  return { activeStage, stageStatuses }
}
