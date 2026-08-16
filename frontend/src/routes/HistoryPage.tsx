import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { PageHero } from '@/components/layout/PageHero'
import { InvoiceList } from '@/routes/DashboardPage'
import { Select } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { fetchInvoices } from '@/lib/api/invoices'
import type { InvoiceRun } from '@/types'

const FILTERS = [
  { value: '', label: 'All statuses' },
  { value: 'stage1_passed', label: 'Stage 1 passed' },
  { value: 'needs_human_review', label: 'Needs human review' },
  { value: 'extraction_failed', label: 'Extraction failed' },
]

export function HistoryPage() {
  const [status, setStatus] = useState('')
  const query = useQuery({
    queryKey: ['invoices', { status, limit: 50 }],
    queryFn: () => fetchInvoices({ status: status || undefined, limit: 50 }),
  })

  return (
    <>
      <PageHero title="History" subtitle="Browse all processed invoices." />

      <div className="mb-6 max-w-xs">
        <Select value={status} onChange={(e) => setStatus(e.target.value)}>
          {FILTERS.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </Select>
      </div>

      {query.isLoading ? (
        <Skeleton className="h-60" />
      ) : query.isError ? (
        <p className="text-sm text-danger">Failed to load invoices. Is the API running?</p>
      ) : (
        <InvoiceList rows={(query.data?.invoices ?? []) as unknown as InvoiceRun[]} />
      )}
    </>
  )
}
