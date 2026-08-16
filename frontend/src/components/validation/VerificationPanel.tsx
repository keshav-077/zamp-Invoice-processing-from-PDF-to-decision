import type { VerificationResult } from '@/types'
import { Badge } from '@/components/ui/badge'

export function VerificationPanel({ verification }: { verification: VerificationResult | null | undefined }) {
  if (!verification) return <p className="text-sm text-muted">No verification data.</p>

  const variant =
    verification.verification_status === 'pass'
      ? 'success'
      : verification.verification_status === 'flag'
        ? 'warning'
        : 'danger'

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Badge variant={variant}>{verification.verification_status.toUpperCase()}</Badge>
        <span className="text-sm text-muted">
          Confidence: {(verification.overall_confidence * 100).toFixed(0)}%
        </span>
      </div>
      {verification.issues?.length ? (
        <ul className="space-y-2">
          {verification.issues.map((issue, i) => (
            <li key={i} className="rounded-xl border border-border px-4 py-3 text-sm">
              <span className="font-medium">{issue.field}</span>
              <Badge variant="muted" className="ml-2">
                {issue.severity}
              </Badge>
              <p className="mt-1 text-muted">{issue.reason}</p>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted">No issues reported.</p>
      )}
    </div>
  )
}
