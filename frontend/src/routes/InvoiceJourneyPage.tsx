import { Navigate, Outlet, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { AnimatePresence } from 'framer-motion'
import { Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { fetchInvoice } from '@/lib/api/invoices'
import { normalizeInvoiceRun } from '@/lib/normalize'
import { InvoiceJourneyContext } from '@/contexts/InvoiceJourneyContext'
import { BuyerDecisionBanner } from '@/components/journey/BuyerDecisionBanner'
import { StageTabBar } from '@/components/journey/StageTabBar'
import { AnimatedStageContent } from '@/components/journey/shared/AnimatedStageContent'
import { Skeleton } from '@/components/ui/skeleton'
import type { InvoiceRun, PipelineResult } from '@/types'
import { Stage1View } from '@/components/journey/Stage1View'
import { Stage2View } from '@/components/journey/Stage2View'
import { Stage3View } from '@/components/journey/Stage3View'
import { Stage4View } from '@/components/journey/Stage4View'
import { Stage5View } from '@/components/journey/Stage5View'
import { formatDuration, formatTimestamp } from '@/lib/format'

function StageContent({ stage }: { stage: number }) {
  switch (stage) {
    case 1:
      return <Stage1View />
    case 2:
      return <Stage2View />
    case 3:
      return <Stage3View />
    case 4:
      return <Stage4View />
    case 5:
      return <Stage5View />
    default:
      return <Navigate to="../stage/1" replace />
  }
}

export function InvoiceJourneyShell({
  initialResult,
  showBackLink = true,
}: {
  initialResult?: PipelineResult
  showBackLink?: boolean
}) {
  const { documentId, stageNum } = useParams()
  const id = documentId ?? initialResult?.document_id ?? ''
  const stage = Math.min(5, Math.max(1, Number(stageNum) || 1))

  const query = useQuery({
    queryKey: ['invoice', id],
    queryFn: () => fetchInvoice(id),
    enabled: !!id && !initialResult,
  })

  const result: PipelineResult | null = initialResult
    ? initialResult
    : query.data
      ? normalizeInvoiceRun(query.data as unknown as InvoiceRun)
      : null

  if (!initialResult && query.isLoading) {
    return <Skeleton className="h-96" />
  }

  if (!result) {
    return <p className="text-danger">Invoice not found.</p>
  }

  if (stageNum && Number(stageNum) !== stage) {
    return <Navigate to={`/invoice/${id}/stage/${stage}`} replace />
  }

  return (
    <InvoiceJourneyContext.Provider value={{ result, refresh: () => query.refetch() }}>
      {showBackLink && (
        <Link
          to="/history"
          className="mb-6 inline-flex items-center gap-2 text-sm text-muted hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to history
        </Link>
      )}

      <div className="mb-8 rounded-2xl border border-border bg-surface p-6">
        <p className="font-display text-2xl">{result.filename}</p>
        <p className="mt-1 text-sm text-muted">
          {result.document_id} · {formatTimestamp(result.upload_timestamp)} ·{' '}
          {formatDuration(result.processing_time_seconds)}
        </p>
      </div>

      <BuyerDecisionBanner />

      <StageTabBar result={result} documentId={id} />

      <AnimatePresence mode="wait">
        <AnimatedStageContent stageKey={`stage-${stage}`}>
          <StageContent stage={stage} />
        </AnimatedStageContent>
      </AnimatePresence>

      <Outlet />
    </InvoiceJourneyContext.Provider>
  )
}

export function InvoiceJourneyRedirect() {
  const { documentId } = useParams()
  return <Navigate to={`/invoice/${documentId}/stage/1`} replace />
}
