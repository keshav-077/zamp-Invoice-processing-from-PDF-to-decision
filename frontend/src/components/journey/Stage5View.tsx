import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { useInvoiceJourney } from '@/contexts/InvoiceJourneyContext'
import { StageHeader } from '@/components/journey/shared/StageHeader'
import { SectionCard, IssuesPanel } from '@/components/journey/shared/SectionCard'
import { StaggerSection } from '@/components/journey/shared/AnimatedStageContent'
import { getStage5Summary } from '@/lib/stageSummary'
import { fetchAuditReconstruct } from '@/lib/api/audit'
import { coalesceDict } from '@/lib/normalize'
import { Badge } from '@/components/ui/badge'
import type { NarrativeEntry } from '@/types'

export function Stage5View() {
  const { result } = useInvoiceJourney()
  const summary = getStage5Summary(result)
  const stage5 = coalesceDict(result.stage5_result)
  const narrative = (stage5.narrative ?? []) as NarrativeEntry[]

  const auditQuery = useQuery({
    queryKey: ['audit', result.document_id],
    queryFn: () => fetchAuditReconstruct(result.document_id),
  })

  const gaps = stage5.gaps ?? []
  const controls = stage5.control_verifications ?? []

  return (
    <div>
      <StageHeader stage={5} summary={summary} />

      <StaggerSection index={0}>
        <SectionCard title="Explanation record">
          <div className="flex flex-wrap gap-3 text-sm">
            <Badge variant={summary.outcome === 'pass' ? 'success' : 'warning'}>
              {result.stage5_status || stage5.explanation_status}
            </Badge>
            {result.stage5_explanation_id && (
              <span className="text-muted">ID: {result.stage5_explanation_id}</span>
            )}
            {auditQuery.data && (
              <span className="text-muted">
                Audit integrity: {auditQuery.data.integrity_status}
              </span>
            )}
          </div>
        </SectionCard>
      </StaggerSection>

      <div className="mt-8 space-y-8">
        <StaggerSection index={1}>
          <SectionCard title="Why this decision was made" description="Deterministic narrative from rule engine">
            <ol className="relative space-y-0 border-l border-border pl-6">
              {narrative.map((entry, i) => (
                <motion.li
                  key={i}
                  className="relative pb-8 last:pb-0"
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.08, duration: 0.3 }}
                >
                  <span className="absolute -left-[25px] top-1 h-3 w-3 rounded-full border-2 border-accent bg-background" />
                  <p className="text-sm leading-relaxed">
                    {entry.icon ? `${entry.icon} ` : ''}
                    {entry.text}
                  </p>
                  {entry.source_rule_id && (
                    <p className="mt-1 text-xs text-muted">
                      {entry.source_rule_id} · {entry.category}
                    </p>
                  )}
                </motion.li>
              ))}
              {!narrative.length && (
                <p className="text-sm text-muted">No narrative steps recorded.</p>
              )}
            </ol>
          </SectionCard>
        </StaggerSection>

        {gaps.length > 0 && (
          <StaggerSection index={2}>
            <IssuesPanel
              issues={gaps.map((g) => `Stage ${g.stage}: ${g.reason}`)}
            />
          </StaggerSection>
        )}

        {controls.length > 0 && (
          <StaggerSection index={3}>
            <SectionCard title="Control verifications">
              <ul className="space-y-2 text-sm">
                {controls.map((c) => (
                  <li key={c.control_id} className="flex justify-between gap-2">
                    <span>{c.control_id}</span>
                    <Badge variant="muted">{c.status}</Badge>
                  </li>
                ))}
              </ul>
            </SectionCard>
          </StaggerSection>
        )}

        <StaggerSection index={4}>
          <details className="rounded-2xl border border-border bg-surface p-4">
            <summary className="cursor-pointer text-sm font-medium text-muted">
              Technical audit (full JSON)
            </summary>
            <pre className="mt-4 max-h-96 overflow-auto text-xs">
              {JSON.stringify(auditQuery.data ?? result, null, 2)}
            </pre>
          </details>
        </StaggerSection>
      </div>
    </div>
  )
}
