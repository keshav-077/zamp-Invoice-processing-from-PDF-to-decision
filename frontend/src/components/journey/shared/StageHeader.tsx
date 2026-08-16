import { Badge } from '@/components/ui/badge'
import type { StageSummary } from '@/lib/stageSummary'
import { STAGE_TITLES } from '@/lib/stageLabels'

export function StageHeader({ stage, summary }: { stage: number; summary: StageSummary }) {
  const variant =
    summary.outcome === 'pass'
      ? 'success'
      : summary.outcome === 'warn'
        ? 'warning'
        : summary.outcome === 'fail'
          ? 'danger'
          : 'muted'

  return (
    <div className="mb-8 space-y-3 border-b border-border pb-8">
      <p className="text-xs uppercase tracking-widest text-muted">Stage {stage}</p>
      <div className="flex flex-wrap items-center gap-4">
        <h2 className="font-display text-3xl tracking-tight md:text-4xl">{STAGE_TITLES[stage]}</h2>
        <Badge variant={variant}>{summary.badge}</Badge>
      </div>
      <p className="max-w-2xl text-base text-muted">{summary.summary}</p>
    </div>
  )
}
