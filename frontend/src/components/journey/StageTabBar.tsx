import { Link, useParams } from 'react-router-dom'
import { Check, AlertTriangle, X, Minus } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { PipelineResult } from '@/types'
import { getStageSummary, type StageOutcome } from '@/lib/stageSummary'
import { STAGE_TITLES } from '@/lib/stageLabels'

function OutcomeIcon({ outcome }: { outcome: StageOutcome }) {
  if (outcome === 'pass') return <Check className="h-3.5 w-3.5 text-success" />
  if (outcome === 'warn') return <AlertTriangle className="h-3.5 w-3.5 text-warning" />
  if (outcome === 'fail') return <X className="h-3.5 w-3.5 text-danger" />
  return <Minus className="h-3.5 w-3.5 text-muted" />
}

export function StageTabBar({ result, documentId }: { result: PipelineResult; documentId: string }) {
  const { stageNum } = useParams()
  const active = Number(stageNum) || 1

  return (
    <nav className="mb-10 flex flex-wrap gap-2 border-b border-border pb-6">
      {[1, 2, 3, 4, 5].map((n) => {
        const summary = getStageSummary(result, n)
        const isActive = active === n
        return (
          <Link
            key={n}
            to={`/invoice/${documentId}/stage/${n}`}
            className={cn(
              'flex items-center gap-2 rounded-full border px-4 py-2 text-sm transition-all',
              isActive
                ? 'border-white/20 bg-white/10 text-foreground'
                : 'border-border text-muted hover:border-white/10 hover:text-foreground',
            )}
          >
            <span className="font-medium">Stage {n}</span>
            <span className="hidden sm:inline">{STAGE_TITLES[n]}</span>
            <OutcomeIcon outcome={summary.outcome} />
          </Link>
        )
      })}
    </nav>
  )
}
