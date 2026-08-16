import { useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { useEffect, useState } from 'react'
import { PageHero } from '@/components/layout/PageHero'
import { FileUploadZone } from '@/components/pipeline/FileUploadZone'
import { StageProgressRail } from '@/components/journey/StageProgressRail'
import { Button } from '@/components/ui/button'
import { uploadInvoiceAsync } from '@/lib/api/jobs'
import { uploadInvoice as uploadInvoiceSync } from '@/lib/api/invoices'
import { useJobProgress } from '@/hooks/useJobProgress'
import { useAnimatedPipelineProgress } from '@/hooks/useAnimatedPipelineProgress'
import { ApiError } from '@/lib/api/client'

const USE_ASYNC_JOBS = import.meta.env.VITE_USE_ASYNC_JOBS !== 'false'

export function UploadPage() {
  const [file, setFile] = useState<File | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const navigate = useNavigate()

  const syncMutation = useMutation({
    mutationFn: uploadInvoiceSync,
    onSuccess: (data) => {
      toast.success('Processing complete')
      navigate(`/invoice/${data.document_id}/stage/1`, { state: { result: data } })
    },
    onError: (err: Error) => {
      toast.error(err instanceof ApiError ? err.detail : err.message)
    },
  })

  const asyncMutation = useMutation({
    mutationFn: uploadInvoiceAsync,
    onSuccess: (data) => {
      setJobId(data.job_id)
      toast.message('Processing started')
    },
    onError: (err: Error) => {
      toast.error(err instanceof ApiError ? err.detail : err.message)
    },
  })

  const jobProgress = useJobProgress(jobId, !!jobId)
  const animated = useAnimatedPipelineProgress(
    syncMutation.isPending,
    syncMutation.isSuccess,
    syncMutation.isError,
  )

  useEffect(() => {
    if (jobProgress.isComplete && jobProgress.documentId) {
      toast.success('Processing complete')
      navigate(`/invoice/${jobProgress.documentId}/stage/1`)
    }
  }, [jobProgress.isComplete, jobProgress.documentId, navigate])

  const processing = USE_ASYNC_JOBS
    ? asyncMutation.isPending || (!!jobId && !jobProgress.isComplete && !jobProgress.isFailed)
    : syncMutation.isPending

  const showRail = USE_ASYNC_JOBS
    ? asyncMutation.isSuccess || asyncMutation.isPending || !!jobId
    : syncMutation.isPending || syncMutation.isSuccess || syncMutation.isError

  const activeStage = USE_ASYNC_JOBS ? jobProgress.activeStage : animated.activeStage
  const stageStatuses = USE_ASYNC_JOBS ? jobProgress.stageStatuses : animated.stageStatuses
  const error = USE_ASYNC_JOBS
    ? jobProgress.error || (asyncMutation.isError ? String(asyncMutation.error) : null)
    : syncMutation.isError
      ? syncMutation.error instanceof ApiError
        ? syncMutation.error.detail
        : syncMutation.error?.message
      : null

  const handleUpload = () => {
    if (!file) return
    if (USE_ASYNC_JOBS) {
      asyncMutation.mutate(file)
    } else {
      syncMutation.mutate(file)
    }
  }

  return (
    <>
      <PageHero
        title="Upload Invoice"
        subtitle="Process a PDF or image through Stages 1–5 with real backend progress."
      />

      <div className="mx-auto max-w-3xl space-y-8">
        {!showRail && (
          <>
            <FileUploadZone file={file} onFileSelect={setFile} disabled={processing} />
            <Button className="w-full" size="lg" disabled={!file || processing} onClick={handleUpload}>
              Process Invoice
            </Button>
          </>
        )}

        {showRail && (
          <StageProgressRail
            activeStage={activeStage}
            stageStatuses={stageStatuses}
            error={error ?? null}
          />
        )}

        {jobProgress.isComplete && (
          <p className="text-center text-sm text-muted">Opening results…</p>
        )}
      </div>
    </>
  )
}
