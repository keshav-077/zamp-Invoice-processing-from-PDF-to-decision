import { useInvoiceJourney } from '@/contexts/InvoiceJourneyContext'
import { StageHeader } from '@/components/journey/shared/StageHeader'
import { SectionCard, MetricRow, IssuesPanel } from '@/components/journey/shared/SectionCard'
import { StaggerSection } from '@/components/journey/shared/AnimatedStageContent'
import { getStage1Summary, avgFieldConfidence, splitDecisionExplanation } from '@/lib/stageSummary'
import { ExtractionTable } from '@/components/extraction/ExtractionTable'
import { LineItemsTable } from '@/components/extraction/LineItemsTable'
import { VerificationPanel } from '@/components/validation/VerificationPanel'
import { ArithmeticPanel, ReconciliationPanel } from '@/components/validation/ReconciliationPanel'
import { formatDuration } from '@/lib/format'
import { num } from '@/lib/normalize'
import { CheckCircle2 } from 'lucide-react'

const SUB_STEPS = [
  'Input validation & preprocessing',
  'Page classification',
  'Primary extraction (LLM)',
  'Independent verification (LLM)',
  'Reconciliation & routing',
]

export function Stage1View() {
  const { result } = useInvoiceJourney()
  const summary = getStage1Summary(result)
  const stageLines = splitDecisionExplanation(result.decision_explanation)[1]

  const fieldCount = result.extraction
    ? Object.values(result.extraction).filter(
        (v) => v && typeof v === 'object' && 'value' in v && (v as { value: unknown }).value,
      ).length
    : 0

  const issues: string[] = []
  result.verification?.issues?.forEach((i) => issues.push(`${i.field}: ${i.reason}`))
  result.reconciliation?.checks
    ?.filter((c) => c.status === 'fail')
    .forEach((c) => issues.push(c.detail ?? c.check_name))
  if (result.extraction) {
    const lowConf = [
      result.extraction.vendor_name,
      result.extraction.invoice_number,
      result.extraction.total_amount,
    ].filter((f) => f && num(f.confidence) < 0.7 && f.value)
    lowConf.forEach((f) => issues.push(`Low confidence on extracted field (${Math.round(num(f?.confidence) * 100)}%)`))
  }

  return (
    <div>
      <StageHeader stage={1} summary={summary} />

      <StaggerSection index={0}>
        <MetricRow
          metrics={[
            { label: 'Fields extracted', value: String(fieldCount) },
            { label: 'Avg confidence', value: `${Math.round(avgFieldConfidence(result) * 100)}%` },
            {
              label: 'Verification',
              value: result.verification?.verification_status?.toUpperCase() ?? '—',
            },
            {
              label: 'Reconciliation',
              value: result.reconciliation?.overall_status ?? '—',
            },
          ]}
        />
      </StaggerSection>

      <div className="mt-8 space-y-8">
        <StaggerSection index={1}>
          <SectionCard title="Processing checklist" description="Steps completed in Stage 1">
            <ul className="space-y-2">
              {SUB_STEPS.map((step) => (
                <li key={step} className="flex items-center gap-2 text-sm">
                  <CheckCircle2 className="h-4 w-4 text-success" />
                  {step}
                </li>
              ))}
            </ul>
            <p className="mt-4 text-xs text-muted">
              Processed in {formatDuration(result.processing_time_seconds)} · Document{' '}
              {result.document_id}
            </p>
          </SectionCard>
        </StaggerSection>

        {stageLines.length > 0 && (
          <StaggerSection index={2}>
            <SectionCard title="Stage 1 summary">
              <ul className="space-y-1 text-sm text-muted">
                {stageLines.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
            </SectionCard>
          </StaggerSection>
        )}

        <StaggerSection index={3}>
          <SectionCard title="Extracted fields" description="Values read from the invoice with confidence scores">
            <ExtractionTable extraction={result.extraction} />
          </SectionCard>
        </StaggerSection>

        <StaggerSection index={4}>
          <SectionCard title="Line items">
            <LineItemsTable extraction={result.extraction} />
          </SectionCard>
        </StaggerSection>

        <StaggerSection index={5}>
          <SectionCard title="Independent verification" description="Second LLM pass challenging extraction">
            <VerificationPanel verification={result.verification} />
          </SectionCard>
        </StaggerSection>

        <StaggerSection index={6}>
          <SectionCard title="Reconciliation" description="Totals and charge arithmetic">
            <ReconciliationPanel reconciliation={result.reconciliation} />
            <ArithmeticPanel arithmetic={result.arithmetic} />
          </SectionCard>
        </StaggerSection>

        {issues.length > 0 && (
          <StaggerSection index={7}>
            <IssuesPanel issues={issues} critical={summary.outcome === 'fail'} />
          </StaggerSection>
        )}

        <details className="rounded-2xl border border-border bg-surface p-4 text-sm">
          <summary className="cursor-pointer font-medium text-muted">Technical details</summary>
          <pre className="mt-4 overflow-auto text-xs">{JSON.stringify(result.arithmetic, null, 2)}</pre>
        </details>
      </div>
    </div>
  )
}
