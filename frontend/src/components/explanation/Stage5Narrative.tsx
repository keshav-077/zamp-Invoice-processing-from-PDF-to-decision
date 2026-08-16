import type { PipelineResult } from '@/types'
import { coalesceDict, parseJsonField } from '@/lib/normalize'
import { Badge } from '@/components/ui/badge'

export function Stage5Narrative({ result }: { result: PipelineResult }) {
  const stage5 =
    coalesceDict(result.stage5_result) ||
    coalesceDict(parseJsonField(result.stage5_result))
  const status = result.stage5_status || stage5.explanation_status || ''
  const explanationId = result.stage5_explanation_id || stage5.explanation_id

  if (!status && !Object.keys(stage5).length) {
    return <p className="text-sm text-muted">No Stage 5 explanation available.</p>
  }

  const narrative = stage5.narrative ?? []

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <Badge variant={status === 'COMPLETE' ? 'success' : 'warning'}>{status || 'UNKNOWN'}</Badge>
        {explanationId && (
          <span className="text-xs text-muted">ID: {explanationId}</span>
        )}
      </div>

      {(stage5.decision_outcome || result.stage4_decision) && (
        <p className="text-sm">
          Decision: <code>{stage5.decision_outcome ?? result.stage4_decision}</code>
          {(stage5.decision_substate || result.stage4_status) &&
            ` / ${stage5.decision_substate ?? result.stage4_status}`}
        </p>
      )}

      {narrative.length > 0 && (
        <div className="space-y-3">
          <p className="text-sm font-medium">Why this decision was made</p>
          <ul className="space-y-2">
            {narrative.map((entry, i) => (
              <li key={i} className="rounded-xl border border-border px-4 py-3 text-sm">
                {entry.icon ? `${entry.icon} ` : ''}
                {entry.text}
                {entry.source_rule_id && (
                  <p className="mt-1 text-xs text-muted">
                    {entry.source_rule_id} · {entry.category}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {stage5.gaps?.length ? (
        <div>
          <p className="mb-2 text-sm font-medium">Evidence gaps</p>
          <ul className="space-y-1 text-sm text-muted">
            {stage5.gaps.map((gap, i) => (
              <li key={i}>
                Stage {gap.stage}: {gap.reason}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}
