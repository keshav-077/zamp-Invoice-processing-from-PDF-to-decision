import type { ArithmeticResult, ReconciliationResult } from '@/types'
import { num } from '@/lib/normalize'
import { CheckCircle2, XCircle, AlertTriangle, Minus } from 'lucide-react'

function CheckIcon({ status }: { status: string }) {
  if (status === 'pass') return <CheckCircle2 className="h-4 w-4 text-success" />
  if (status === 'fail') return <XCircle className="h-4 w-4 text-danger" />
  if (status === 'review') return <AlertTriangle className="h-4 w-4 text-warning" />
  return <Minus className="h-4 w-4 text-muted" />
}

export function ReconciliationPanel({
  reconciliation,
}: {
  reconciliation: ReconciliationResult | null | undefined
}) {
  if (!reconciliation) return <p className="text-sm text-muted">No reconciliation data.</p>

  return (
    <div className="space-y-4">
      <p className="text-sm">
        Status: <code className="rounded bg-white/5 px-2 py-0.5">{reconciliation.overall_status}</code>
      </p>
      {reconciliation.residual_amount != null && (
        <p className="text-sm text-muted">Residual: {num(reconciliation.residual_amount).toFixed(2)}</p>
      )}
      {reconciliation.inferred_charges?.map((c, i) => (
        <p key={i} className="text-sm text-muted">
          Inferred: {c.label} = {c.amount}
        </p>
      ))}
      <ul className="space-y-2">
        {reconciliation.checks?.map((check, i) => (
          <li key={i} className="flex items-start gap-2 text-sm">
            <CheckIcon status={check.status} />
            <span>{check.detail ?? check.check_name}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function ArithmeticPanel({ arithmetic }: { arithmetic: ArithmeticResult | null | undefined }) {
  if (!arithmetic) return null

  return (
    <div className="mt-6 space-y-2 border-t border-border pt-6">
      <p className="text-sm font-medium">Arithmetic Checks</p>
      <ul className="space-y-2">
        {arithmetic.checks?.map((check, i) => (
          <li key={i} className="flex items-start gap-2 text-sm">
            <CheckIcon status={check.status} />
            <span>{check.detail ?? check.check_name}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
