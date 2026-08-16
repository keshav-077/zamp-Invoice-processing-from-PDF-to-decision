import { useInvoiceJourney } from '@/contexts/InvoiceJourneyContext'
import { StageHeader } from '@/components/journey/shared/StageHeader'
import { SectionCard, MetricRow, IssuesPanel } from '@/components/journey/shared/SectionCard'
import { StaggerSection } from '@/components/journey/shared/AnimatedStageContent'
import { getStage3Summary, splitDecisionExplanation } from '@/lib/stageSummary'
import { labelReasonCode } from '@/lib/stageLabels'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { ValidationCheck } from '@/types'

function checkVariant(status: string) {
  if (status === 'PASS') return 'success'
  if (status === 'FAIL') return 'danger'
  if (status === 'FLAG') return 'warning'
  return 'muted'
}

export function Stage3View() {
  const { result } = useInvoiceJourney()
  const summary = getStage3Summary(result)
  const report = result.stage3_result
  const checks = report?.checks ? Object.values(report.checks) : []
  const stageLines = splitDecisionExplanation(result.decision_explanation)[3]
  const validationRan = Boolean(report?.checks && checks.length > 0)

  const passed = checks.filter((c) => c.status === 'PASS').length
  const failed = checks.filter((c) => c.status === 'FAIL').length
  const flagged = checks.filter((c) => c.status === 'FLAG').length

  const issues: string[] = []
  report?.controls?.forEach((c) => {
    const label = labelReasonCode(c.reason_code)
    issues.push(`${c.control_type}: ${label.title} — ${c.detail || label.description}`)
  })
  checks
    .filter((c) => c.status === 'FAIL' || c.status === 'FLAG')
    .forEach((c) => {
      issues.push(`${c.check_id}: ${c.reason_code || c.status}`)
    })

  return (
    <div>
      <StageHeader stage={3} summary={summary} />

      <StaggerSection index={0}>
        <MetricRow
          metrics={[
            { label: 'Overall state', value: report?.overall_state ?? result.stage3_status ?? '—' },
            { label: 'Checks passed', value: String(passed) },
            { label: 'Flagged', value: String(flagged) },
            { label: 'Failed', value: String(failed) },
          ]}
        />
      </StaggerSection>

      <div className="mt-8 space-y-8">
        {stageLines.length > 0 && (
          <StaggerSection index={1}>
            <SectionCard title="Validation summary">
              <ul className="space-y-1 text-sm text-muted">
                {stageLines.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
            </SectionCard>
          </StaggerSection>
        )}

        <StaggerSection index={2}>
          <SectionCard
            title="Validation engines"
            description={
              validationRan
                ? 'Seven independent control checks'
                : 'Validation did not run — awaiting PO confirmation or stronger match evidence'
            }
          >
            <div className="divide-y divide-border">
              {checks.map((check: ValidationCheck) => (
                <div
                  key={check.check_id}
                  className="flex flex-wrap items-start justify-between gap-3 py-4 first:pt-0 last:pb-0"
                >
                  <div>
                    <p className="font-medium">{check.check_id.replace(/_/g, ' ')}</p>
                    {check.reason_code && (
                      <p className="mt-1 text-sm text-muted">
                        {labelReasonCode(check.reason_code).description}
                      </p>
                    )}
                    {check.evidence?.slice(0, 2).map((e, i) => (
                      <p key={i} className="mt-1 text-xs text-muted">
                        • {e}
                      </p>
                    ))}
                  </div>
                  <Badge variant={checkVariant(check.status)}>{check.status}</Badge>
                </div>
              ))}
              {!checks.length && <p className="text-sm text-muted">No check details available.</p>}
            </div>
          </SectionCard>
        </StaggerSection>

        {report?.controls?.length ? (
          <StaggerSection index={3}>
            <SectionCard title="Active controls" description="Hold and block controls triggered">
              <div className="space-y-3">
                {report.controls.map((ctrl) => {
                  const label = labelReasonCode(ctrl.reason_code)
                  return (
                    <div
                      key={ctrl.control_id}
                      className={cn(
                        'rounded-xl border p-4',
                        ctrl.control_type === 'BLOCK'
                          ? 'border-danger/30 bg-danger/5'
                          : 'border-warning/30 bg-warning/5',
                      )}
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant={ctrl.control_type === 'BLOCK' ? 'danger' : 'warning'}>
                          {ctrl.control_type}
                        </Badge>
                        <span className="font-medium">{label.title}</span>
                      </div>
                      <p className="mt-2 text-sm text-muted">{ctrl.detail || label.description}</p>
                    </div>
                  )
                })}
              </div>
            </SectionCard>
          </StaggerSection>
        ) : null}

        {report?.reason_codes?.length ? (
          <StaggerSection index={4}>
            <SectionCard title="Reason codes">
              <ul className="space-y-2">
                {report.reason_codes.map((code) => {
                  const label = labelReasonCode(code)
                  return (
                    <li key={code} className="text-sm">
                      <span className="font-medium">{label.title}</span>
                      <span className="text-muted"> — {label.description}</span>
                    </li>
                  )
                })}
              </ul>
            </SectionCard>
          </StaggerSection>
        ) : null}

        {issues.length > 0 && (
          <StaggerSection index={5}>
            <IssuesPanel issues={issues} critical={summary.outcome === 'fail'} />
          </StaggerSection>
        )}
      </div>
    </div>
  )
}
