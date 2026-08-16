import { motion } from 'framer-motion'
import { Check, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { STAGE_TITLES } from '@/lib/stageLabels'

export type RailStageStatus = 'pending' | 'active' | 'done' | 'error'

interface StageProgressRailProps {
  /** 1-5: current active stage during processing */
  activeStage: number
  stageStatuses: RailStageStatus[]
  error?: string | null
}

export function StageProgressRail({ activeStage, stageStatuses, error }: StageProgressRailProps) {
  return (
    <div className="rounded-2xl border border-border bg-surface p-6">
      <h3 className="mb-6 text-sm font-medium uppercase tracking-wider text-muted">
        Pipeline progress
      </h3>
      <div className="relative flex flex-col gap-0 md:flex-row md:items-start md:justify-between">
        {[1, 2, 3, 4, 5].map((n, i) => {
          const status = stageStatuses[n - 1] ?? 'pending'
          const isLast = i === 4
          return (
            <div key={n} className="relative flex flex-1 flex-col items-center pb-8 md:pb-0">
              {!isLast && (
                <div
                  className="absolute left-1/2 top-5 hidden h-0.5 w-full md:block"
                  aria-hidden
                >
                  <motion.div
                    className={cn(
                      'h-full origin-left',
                      status === 'done' ? 'bg-success' : 'bg-white/10',
                    )}
                    initial={{ scaleX: 0 }}
                    animate={{ scaleX: status === 'done' || activeStage > n ? 1 : 0 }}
                    transition={{ duration: 0.5, ease: 'easeOut' }}
                  />
                </div>
              )}
              <motion.div
                className={cn(
                  'relative z-10 flex h-10 w-10 items-center justify-center rounded-full border-2',
                  status === 'done' && 'border-success bg-success/10',
                  status === 'active' && 'border-accent bg-accent/10',
                  status === 'error' && 'border-danger bg-danger/10',
                  status === 'pending' && 'border-border bg-surface-elevated',
                )}
                animate={status === 'active' ? { scale: [1, 1.08, 1] } : { scale: 1 }}
                transition={status === 'active' ? { repeat: Infinity, duration: 1.5 } : {}}
              >
                {status === 'done' ? (
                  <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }}>
                    <Check className="h-5 w-5 text-success" />
                  </motion.div>
                ) : status === 'active' ? (
                  <Loader2 className="h-5 w-5 animate-spin text-accent" />
                ) : (
                  <span className="text-sm font-medium text-muted">{n}</span>
                )}
              </motion.div>
              <p className="mt-3 text-center text-xs font-medium">{STAGE_TITLES[n]}</p>
              <p className="mt-0.5 text-center text-[10px] uppercase tracking-wider text-muted">
                {status === 'done' ? 'Complete' : status === 'active' ? 'Running…' : status === 'error' ? 'Failed' : 'Waiting'}
              </p>
            </div>
          )
        })}
      </div>
      {error && (
        <p className="mt-4 rounded-xl border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
          {error}
        </p>
      )}
    </div>
  )
}
