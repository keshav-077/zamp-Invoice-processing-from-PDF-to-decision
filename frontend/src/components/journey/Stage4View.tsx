import { useInvoiceJourney } from '@/contexts/InvoiceJourneyContext'
import { StageHeader } from '@/components/journey/shared/StageHeader'
import { SectionCard, MetricRow, IssuesPanel } from '@/components/journey/shared/SectionCard'
import { StaggerSection } from '@/components/journey/shared/AnimatedStageContent'
import { getStage4Summary, splitDecisionExplanation } from '@/lib/stageSummary'
import { labelSubstate } from '@/lib/stageLabels'
import {
  isStage4AttentionRule,
  stage4RuleBadgeVariant,
  stage4RuleResultLabel,
} from '@/lib/stage4Rules'
import { Badge } from '@/components/ui/badge'
import type { RuleEvaluation } from '@/types'

export function Stage4View() {
  const { result } = useInvoiceJourney()
  const summary = getStage4Summary(result)
  const decision = result.stage4_result
  const rules = decision?.trace?.rules_evaluated ?? []
  const stageLines = splitDecisionExplanation(result.decision_explanation)[4]

  const triggered = rules.filter((r) => r.result === 'TRIGGERED')
  const issues: string[] = []
  if (result.stage4_decision === 'REJECT') {
    issues.push(labelSubstate(result.stage4_status) || 'Invoice was rejected and will not be paid.')
  }
  rules.filter(isStage4AttentionRule).forEach((r) => {
    if (r.detail) issues.push(`${r.rule_id}: ${r.detail}`)
  })

  return (
    <div>
      <StageHeader stage={4} summary={summary} />

      <StaggerSection index={0}>
        <MetricRow
          metrics={[
            { label: 'Decision', value: result.stage4_decision || '—' },
            { label: 'Substate', value: (result.stage4_status || '—').replace(/_/g, ' ') },
            { label: 'Rules triggered', value: String(triggered.length) },
            { label: 'Rules evaluated', value: String(rules.length) },
          ]}
        />
      </StaggerSection>

      <div className="mt-8 space-y-8">
        <StaggerSection index={1}>
          <SectionCard title="Decision in plain language">
            <p className="text-lg">{labelSubstate(result.stage4_status) || summary.summary}</p>
            {decision?.decision_id && (
              <p className="mt-2 text-xs text-muted">Decision ID: {decision.decision_id}</p>
            )}
          </SectionCard>
        </StaggerSection>

        {stageLines.length > 0 && (
          <StaggerSection index={2}>
            <SectionCard title="Pipeline notes">
              <ul className="space-y-1 text-sm text-muted">
                {stageLines.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
            </SectionCard>
          </StaggerSection>
        )}

        <StaggerSection index={3}>
          <SectionCard title="Rule trace" description="Business rules evaluated for this decision">
            <div className="space-y-2">
              {rules.map((rule: RuleEvaluation) => (
                <div
                  key={rule.rule_id}
                  className="flex flex-wrap items-start justify-between gap-2 rounded-xl border border-border px-4 py-3"
                >
                  <div>
                    <p className="text-sm font-medium">{rule.rule_id.replace(/_/g, ' ')}</p>
                    {rule.detail && <p className="mt-1 text-xs text-muted">{rule.detail}</p>}
                  </div>
                  <Badge variant={stage4RuleBadgeVariant(rule)}>
                    {stage4RuleResultLabel(rule)}
                  </Badge>
                </div>
              ))}
              {!rules.length && <p className="text-sm text-muted">Rule trace not available in stored result.</p>}
            </div>
          </SectionCard>
        </StaggerSection>

        {decision?.evidence_summary?.length ? (
          <StaggerSection index={4}>
            <SectionCard title="Evidence">
              <ul className="space-y-1 text-sm text-muted">
                {decision.evidence_summary.map((e, i) => (
                  <li key={i}>• {e}</li>
                ))}
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
