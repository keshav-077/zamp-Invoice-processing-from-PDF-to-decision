import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export function SectionCard({
  title,
  description,
  children,
  className,
}: {
  title: string
  description?: string
  children: ReactNode
  className?: string
}) {
  return (
    <section className={cn('rounded-2xl border border-border bg-surface p-6', className)}>
      <h3 className="text-base font-semibold">{title}</h3>
      {description && <p className="mt-1 text-sm text-muted">{description}</p>}
      <div className="mt-4">{children}</div>
    </section>
  )
}

export function MetricRow({ metrics }: { metrics: { label: string; value: string }[] }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {metrics.map((m) => (
        <div key={m.label} className="rounded-2xl border border-border bg-surface p-5">
          <p className="text-2xl font-semibold tracking-tight">{m.value}</p>
          <p className="mt-1 text-xs uppercase tracking-wider text-muted">{m.label}</p>
        </div>
      ))}
    </div>
  )
}

export function IssuesPanel({ issues, critical }: { issues: string[]; critical?: boolean }) {
  if (!issues.length) return null
  return (
    <div
      className={cn(
        'rounded-2xl border p-5',
        critical ? 'border-danger/40 bg-danger/5' : 'border-warning/40 bg-warning/5',
      )}
    >
      <h3 className={cn('text-sm font-semibold', critical ? 'text-danger' : 'text-warning')}>
        {critical ? 'Critical issues' : 'Items needing attention'}
      </h3>
      <ul className="mt-3 space-y-2 text-sm text-muted">
        {issues.map((issue, i) => (
          <li key={i}>• {issue}</li>
        ))}
      </ul>
    </div>
  )
}
