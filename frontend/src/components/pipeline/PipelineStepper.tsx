import { cn } from '@/lib/utils'
import { Check, Circle, Loader2, X } from 'lucide-react'

export type StepStatus = 'pending' | 'active' | 'done' | 'error'

export function PipelineStepper({
  steps,
  stepStatus,
}: {
  steps: string[]
  stepStatus: StepStatus
}) {
  return (
    <ol className="space-y-3">
      {steps.map((step, i) => {
        const status: StepStatus =
          stepStatus === 'error' && i === steps.length - 1
            ? 'error'
            : stepStatus === 'active'
              ? i < steps.length - 1
                ? 'done'
                : 'active'
              : stepStatus === 'done'
                ? 'done'
                : 'pending'

        return (
          <li key={step} className="flex items-start gap-3 text-sm">
            <StepIcon status={status} />
            <span className={cn(status === 'pending' && 'text-muted')}>{step}</span>
          </li>
        )
      })}
    </ol>
  )
}

function StepIcon({ status }: { status: StepStatus }) {
  if (status === 'done') return <Check className="mt-0.5 h-4 w-4 text-success" />
  if (status === 'active') return <Loader2 className="mt-0.5 h-4 w-4 animate-spin text-accent" />
  if (status === 'error') return <X className="mt-0.5 h-4 w-4 text-danger" />
  return <Circle className="mt-0.5 h-4 w-4 text-muted" strokeWidth={1} />
}
