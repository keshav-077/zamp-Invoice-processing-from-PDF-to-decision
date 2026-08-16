import { cn } from '@/lib/utils'
import { num } from '@/lib/normalize'
import type { ScoreBreakdown } from '@/types'

const SCORE_KEYS: { key: keyof ScoreBreakdown; label: string; max: number }[] = [
  { key: 'po_match', label: 'PO match', max: 40 },
  { key: 'vendor_match', label: 'Vendor', max: 25 },
  { key: 'line_match', label: 'Lines', max: 20 },
  { key: 'amount_match', label: 'Amount', max: 10 },
  { key: 'date_match', label: 'Date', max: 5 },
]

export function ScoreBreakdownBars({ score }: { score?: ScoreBreakdown }) {
  if (!score) return <p className="text-xs text-muted">No score data</p>

  return (
    <div className="space-y-2">
      {SCORE_KEYS.map(({ key, label, max }) => {
        const val = num(score[key])
        const pct = max > 0 ? Math.min(100, (val / max) * 100) : 0
        return (
          <div key={key}>
            <div className="mb-1 flex justify-between text-xs">
              <span className="text-muted">{label}</span>
              <span>
                {val.toFixed(0)}/{max}
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
              <div
                className={cn('h-full rounded-full bg-accent transition-all duration-500')}
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}
