import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { PageHero } from '@/components/layout/PageHero'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { DecisionBadge } from '@/components/results/DecisionBadge'
import { fetchInvoices, fetchStats } from '@/lib/api/invoices'
import { normalizeInvoiceRun } from '@/lib/normalize'
import type { InvoiceRun } from '@/types'
import { formatDuration, formatTimestamp } from '@/lib/format'

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <Card className="p-6">
      <p className="text-3xl font-semibold tracking-tight">{value}</p>
      <p className="mt-1 text-sm text-muted">{label}</p>
    </Card>
  )
}

export function DashboardPage() {
  const statsQuery = useQuery({ queryKey: ['stats'], queryFn: fetchStats })
  const invoicesQuery = useQuery({
    queryKey: ['invoices', { limit: 10 }],
    queryFn: () => fetchInvoices({ limit: 10 }),
  })

  return (
    <>
      <PageHero title="Dashboard" subtitle="Processing overview and recent activity." />

      {statsQuery.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      ) : statsQuery.data ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Total Processed" value={statsQuery.data.total_invoices} />
          <StatCard label="Stage 1 Passed" value={statsQuery.data.stage1_passed} />
          <StatCard label="Human Review" value={statsQuery.data.needs_human_review} />
          <StatCard
            label="Avg Process Time"
            value={`${statsQuery.data.avg_processing_time.toFixed(1)}s`}
          />
        </div>
      ) : null}

      <section className="mt-12">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-xl font-semibold">Recent Invoices</h2>
          <Link to="/history" className="text-sm text-accent hover:underline">
            View all
          </Link>
        </div>

        {invoicesQuery.isLoading ? (
          <Skeleton className="h-40" />
        ) : (
          <InvoiceList rows={(invoicesQuery.data?.invoices ?? []) as unknown as InvoiceRun[]} />
        )}
      </section>
    </>
  )
}

export function InvoiceList({ rows }: { rows: InvoiceRun[] }) {
  if (!rows.length) {
    return <p className="text-sm text-muted">No invoices processed yet.</p>
  }

  return (
    <div className="divide-y divide-border rounded-2xl border border-border">
      {rows.map((row) => {
        const inv = normalizeInvoiceRun(row)
        return (
          <Link
            key={inv.document_id}
            to={`/invoice/${inv.document_id}/stage/1`}
            className="flex flex-wrap items-center justify-between gap-4 px-4 py-4 transition-colors hover:bg-white/[0.02]"
          >
            <div>
              <p className="font-medium">{inv.filename}</p>
              <p className="text-xs text-muted">{formatTimestamp(inv.upload_timestamp)}</p>
            </div>
            <div className="flex items-center gap-4">
              <DecisionBadge status={inv.status} />
              <span className="text-sm text-muted">{formatDuration(inv.processing_time_seconds)}</span>
            </div>
          </Link>
        )
      })}
    </div>
  )
}
