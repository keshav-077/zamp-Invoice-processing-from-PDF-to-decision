import { useInvoiceJourney } from '@/contexts/InvoiceJourneyContext'
import { StageHeader } from '@/components/journey/shared/StageHeader'
import { SectionCard, MetricRow, IssuesPanel } from '@/components/journey/shared/SectionCard'
import { StaggerSection } from '@/components/journey/shared/AnimatedStageContent'
import { ScoreBreakdownBars } from '@/components/journey/ScoreBreakdownBars'
import { POSuggestionsList } from '@/components/matching/POSuggestionsList'
import { EvidenceComparePanel } from '@/components/journey/EvidenceComparePanel'
import {
  getStage2Summary,
  getStage2TopScore,
  splitDecisionExplanation,
} from '@/lib/stageSummary'
import { coalesceDict, scoreTotal } from '@/lib/normalize'
import type { Stage2Result } from '@/types'
import { Card } from '@/components/ui/card'

const AUTO_MATCHED = new Set(['high_confidence_match', 'matched'])

function topCandidateVendorScore(s2: Stage2Result): number {
  const top = s2.matched_pos?.[0] ?? s2.suggested_candidates?.[0]
  const score = top?.score as Record<string, unknown> | undefined
  return Number(score?.vendor_match ?? 0)
}

export function Stage2View() {
  const { result } = useInvoiceJourney()
  const summary = getStage2Summary(result)
  const s2 = coalesceDict(result.stage2_result) as Stage2Result
  const matched = s2.matched_pos ?? []
  const suggested = s2.suggested_candidates ?? []
  const candidates = suggested.length ? suggested : matched
  const stageLines = splitDecisionExplanation(result.decision_explanation)[2]
  const matchStatus = s2.match_status ?? result.stage2_status ?? ''
  const autoMatched = AUTO_MATCHED.has(matchStatus) && matched.length > 0
  const vendorScore = topCandidateVendorScore(s2)
  const poAligned =
    s2.vendor_master_status === 'po_aligned' ||
    (autoMatched && vendorScore > 0)

  const issues: string[] = []
  const resolverMiss = s2.evidence?.some((e) => e.toLowerCase().includes('no vendor match'))
  if (resolverMiss && !poAligned && !autoMatched) {
    issues.push('Vendor on invoice does not match any vendor in the database.')
  } else if (poAligned && resolverMiss) {
    issues.push('Vendor linked from matched imported PO (name equivalent to invoice).')
  }
  if (summary.outcome === 'warn' && s2.match_status === 'ambiguous_match') {
    issues.push('Multiple POs scored similarly — confirm the correct match manually.')
  }
  candidates.forEach((c) => {
    const total = scoreTotal(c.score as Record<string, unknown>)
    if (total < 10) issues.push(`${c.po_number}: very low match score (${total.toFixed(0)}/100)`)
    if (c.retrieval_method === 'source_record_po_hint') {
      issues.push(
        `${c.po_number}: surfaced from imported transaction PO reference (hint only — confirm manually).`,
      )
    }
  })

  const showSuggestionSubtitle =
    s2.suggestion_mode &&
    !autoMatched &&
    matchStatus !== 'high_confidence_match' &&
    matchStatus !== 'matched'

  const showConfirmPanel =
    !autoMatched &&
    (matchStatus === 'suggested_po_match' ||
      matchStatus === 'ambiguous_match' ||
      matchStatus === 'waiting_for_po' ||
      matched.length === 0)

  return (
    <div>
      <StageHeader stage={2} summary={summary} />

      <StaggerSection index={0}>
        {showSuggestionSubtitle && (
          <p className="mb-3 text-sm text-muted">
            {s2.po_presence === 'non_po'
              ? 'No PO on invoice — candidates are suggestions ranked by vendor, amount, and lines.'
              : 'PO matching used suggestion mode — confirm the best candidate before validation.'}
          </p>
        )}
        {autoMatched && s2.po_presence === 'non_po' && (
          <p className="mb-3 text-sm text-muted">
            No PO on invoice — matched imported master PO by vendor and amount.
          </p>
        )}
        <MetricRow
          metrics={[
            { label: 'PO on invoice', value: s2.po_presence === 'non_po' ? 'No' : 'Yes' },
            { label: 'Match status', value: matchStatus.replace(/_/g, ' ') },
            { label: 'Top score', value: `${getStage2TopScore(result).toFixed(0)}/100` },
            { label: 'Candidates', value: String(candidates.length) },
          ]}
        />
      </StaggerSection>

      <StaggerSection index={0}>
        <EvidenceComparePanel />
      </StaggerSection>

      <div className="mt-8 space-y-8">
        {stageLines.length > 0 && (
          <StaggerSection index={1}>
            <SectionCard title="What happened">
              <ul className="space-y-1 text-sm text-muted">
                {stageLines.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
            </SectionCard>
          </StaggerSection>
        )}

        {s2.evidence?.length ? (
          <StaggerSection index={2}>
            <SectionCard title="Evidence trail">
              <ul className="space-y-1 text-sm text-muted">
                {s2.evidence.map((e, i) => (
                  <li key={i}>• {e}</li>
                ))}
              </ul>
            </SectionCard>
          </StaggerSection>
        ) : null}

        <StaggerSection index={3}>
          <SectionCard
            title="PO candidates"
            description="Ranked by PO number, vendor, line, and amount alignment"
          >
            <div className="space-y-4">
              {candidates.slice(0, 5).map((cand, i) => (
                <Card key={cand.po_number} className="p-4">
                  <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <p className="font-medium">
                        #{i + 1} {cand.po_number}
                        {cand.retrieval_method === 'source_record_po_hint' && (
                          <span className="ml-2 rounded bg-accent/20 px-2 py-0.5 text-xs font-normal text-accent">
                            import hint
                          </span>
                        )}
                      </p>
                      <p className="text-sm text-muted">{cand.vendor_name ?? 'Unknown vendor'}</p>
                    </div>
                    <p className="text-sm">
                      Total{' '}
                      <span className="font-semibold">
                        {scoreTotal(cand.score as Record<string, unknown>).toFixed(0)}
                      </span>
                      /100
                    </p>
                  </div>
                  <ScoreBreakdownBars score={cand.score} />
                </Card>
              ))}
              {!candidates.length && (
                <p className="text-sm text-muted">No PO candidates found.</p>
              )}
            </div>
          </SectionCard>
        </StaggerSection>

        {s2.flags?.length ? (
          <StaggerSection index={4}>
            <IssuesPanel issues={s2.flags} />
          </StaggerSection>
        ) : null}

        {issues.length > 0 && (
          <StaggerSection index={5}>
            <IssuesPanel
              issues={issues}
              critical={summary.outcome === 'fail' && !poAligned}
            />
          </StaggerSection>
        )}

        {showConfirmPanel && (
          <StaggerSection index={6}>
            <SectionCard title="Confirm PO match" description="Human review when auto-match is uncertain">
              <POSuggestionsList
                documentId={result.document_id}
                stage2={result.stage2_result}
                interactive
              />
            </SectionCard>
          </StaggerSection>
        )}
      </div>
    </div>
  )
}
