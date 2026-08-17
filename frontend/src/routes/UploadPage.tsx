import { useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { useEffect, useRef, useState } from 'react'
import { PageHero } from '@/components/layout/PageHero'
import { FileUploadZone } from '@/components/pipeline/FileUploadZone'
import { StageProgressRail } from '@/components/journey/StageProgressRail'
import { Button } from '@/components/ui/button'
import { uploadInvoiceAsync } from '@/lib/api/jobs'
import { uploadInvoice as uploadInvoiceSync } from '@/lib/api/invoices'
import { useJobProgress } from '@/hooks/useJobProgress'
import { useAnimatedPipelineProgress } from '@/hooks/useAnimatedPipelineProgress'
import { formatApiErrorMessage } from '@/lib/api/client'

const USE_ASYNC_JOBS =
  import.meta.env.VITE_USE_ASYNC_JOBS === 'true' ||
  (import.meta.env.VITE_USE_ASYNC_JOBS !== 'false' && import.meta.env.PROD)

export function UploadPage() {
  const [file, setFile] = useState<File | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const jobFailureNotified = useRef<string | null>(null)
  const navigate = useNavigate()

  const syncMutation = useMutation({
    mutationFn: uploadInvoiceSync,
    onMutate: () => setUploadError(null),
    onSuccess: (data) => {
      toast.success(`Invoice processed — opening ${data.document_id}`)
      navigate(`/invoice/${data.document_id}/stage/1`, { state: { result: data } })
    },
    onError: (err: Error) => {
      const msg = formatApiErrorMessage(err, 'Invoice processing failed')
      setUploadError(msg)
      toast.error(msg)
    },
  })

  const asyncMutation = useMutation({
    mutationFn: uploadInvoiceAsync,
    onMutate: () => {
      setUploadError(null)
      jobFailureNotified.current = null
    },
    onSuccess: (data) => {
      setJobId(data.job_id)
      toast.success(`Processing started — ${data.filename ?? 'invoice'}`)
    },
    onError: (err: Error) => {
      const msg = formatApiErrorMessage(err, 'Upload failed — could not start processing')
      setUploadError(msg)
      toast.error(msg)
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

  useEffect(() => {
    if (!jobProgress.isFailed || !jobId) return
    if (jobFailureNotified.current === jobId) return
    jobFailureNotified.current = jobId
    const msg = jobProgress.error?.trim() || 'Invoice processing failed'
    setUploadError(msg)
    toast.error(msg)
  }, [jobProgress.isFailed, jobProgress.error, jobId])

  const processing = USE_ASYNC_JOBS
    ? asyncMutation.isPending || (!!jobId && !jobProgress.isComplete && !jobProgress.isFailed)
    : syncMutation.isPending

  const showRail = USE_ASYNC_JOBS
    ? asyncMutation.isSuccess || asyncMutation.isPending || !!jobId
    : syncMutation.isPending || syncMutation.isSuccess || syncMutation.isError

  const activeStage = USE_ASYNC_JOBS ? jobProgress.activeStage : animated.activeStage
  const stageStatuses = USE_ASYNC_JOBS ? jobProgress.stageStatuses : animated.stageStatuses
  const pipelineError = USE_ASYNC_JOBS
    ? jobProgress.error ||
      (asyncMutation.isError ? formatApiErrorMessage(asyncMutation.error, 'Upload failed') : null)
    : syncMutation.isError
      ? formatApiErrorMessage(syncMutation.error, 'Processing failed')
      : null

  const handleUpload = () => {
    if (!file) return
    setUploadError(null)
    if (USE_ASYNC_JOBS) {
      asyncMutation.mutate(file)
    } else {
      syncMutation.mutate(file)
    }
  }

  const handleReset = () => {
    setFile(null)
    setJobId(null)
    setUploadError(null)
    jobFailureNotified.current = null
    syncMutation.reset()
    asyncMutation.reset()
  }

  return (
    <>
      <PageHero
        title="Upload Invoice"
        subtitle="Process a PDF or image through Stages 1–5 with real backend progress."
      />

      <div className="mx-auto max-w-3xl space-y-8">
        {uploadError && !showRail && (
          <div
            role="alert"
            className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300"
          >
            <p className="font-medium text-red-200">Upload failed</p>
            <p className="mt-1">{uploadError}</p>
          </div>
        )}

        {!showRail && (
          <>
            <FileUploadZone file={file} onFileSelect={setFile} disabled={processing} />
            <Button className="w-full" size="lg" disabled={!file || processing} onClick={handleUpload}>
              {processing ? 'Processing…' : 'Process Invoice'}
            </Button>
          </>
        )}

        {showRail && (
          <StageProgressRail
            activeStage={activeStage}
            stageStatuses={stageStatuses}
            error={pipelineError ?? null}
            statusMessage={
              jobProgress.isRunning
                ? 'Running Stages 1–5 on the server — large invoices can take 1–3 minutes on first load.'
                : null
            }
          />
        )}

        {jobProgress.isComplete && (
          <p className="text-center text-sm text-muted">Opening results…</p>
        )}

        {(uploadError || jobProgress.isFailed) && showRail && (
          <div className="flex justify-center">
            <Button variant="outline" onClick={handleReset}>
              Try another file
            </Button>
          </div>
        )}
      </div>
    </>
  )
}
