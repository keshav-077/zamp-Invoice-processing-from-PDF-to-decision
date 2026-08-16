import { cn } from '@/lib/utils'
import { num } from '@/lib/normalize'

export function ConfidenceBar({ confidence }: { confidence: number }) {
  const pct = Math.round(num(confidence) * 100)
  const color =
    pct >= 90 ? 'bg-success' : pct >= 70 ? 'bg-warning' : 'bg-danger'

  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-white/10">
        <div className={cn('h-full rounded-full', color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-muted">{pct}%</span>
    </div>
  )
}
