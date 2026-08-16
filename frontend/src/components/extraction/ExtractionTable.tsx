import type { InvoiceExtraction } from '@/types'
import { coalesceDict } from '@/lib/normalize'
import { formatCurrency } from '@/lib/format'
import { ConfidenceBar } from './ConfidenceBar'

const FIELDS: { key: keyof InvoiceExtraction; label: string; money?: boolean }[] = [
  { key: 'vendor_name', label: 'Vendor Name' },
  { key: 'invoice_number', label: 'Invoice Number' },
  { key: 'invoice_date', label: 'Invoice Date' },
  { key: 'due_date', label: 'Due Date' },
  { key: 'due_date_terms', label: 'Due Date Terms' },
  { key: 'po_reference', label: 'PO Reference' },
  { key: 'currency', label: 'Currency' },
  { key: 'subtotal', label: 'Subtotal', money: true },
  { key: 'tax_amount', label: 'Tax Amount', money: true },
  { key: 'total_amount', label: 'Total Amount', money: true },
]

export function ExtractionTable({ extraction }: { extraction: InvoiceExtraction | null | undefined }) {
  const data = coalesceDict(extraction)
  if (!extraction) {
    return <p className="text-sm text-muted">No extraction data available.</p>
  }

  const currency = String(data.currency?.value ?? 'USD')

  return (
    <div className="divide-y divide-border rounded-2xl border border-border">
      {FIELDS.map(({ key, label, money }) => {
        const field = data[key] as { value?: unknown; confidence?: number; status?: string } | undefined
        if (!field || typeof field !== 'object' || !('value' in field)) return null
        const value = field.value
        const display =
          value == null || value === ''
            ? 'Not found'
            : money
              ? formatCurrency(value, currency)
              : String(value)

        return (
          <div key={key} className="grid gap-2 px-4 py-3 md:grid-cols-[1fr_auto_auto] md:items-center">
            <div>
              <p className="text-sm font-medium">{label}</p>
              <p className="text-sm text-muted">{display}</p>
            </div>
            <ConfidenceBar confidence={field.confidence ?? 0} />
            <span className="text-xs uppercase text-muted">{field.status ?? '—'}</span>
          </div>
        )
      })}
      {extraction.extra_charges?.length ? (
        <div className="px-4 py-3">
          <p className="mb-2 text-sm font-medium">Extra Charges</p>
          {extraction.extra_charges.map((c, i) => (
            <p key={i} className="text-sm text-muted">
              {c.label} ({c.category}): {c.amount} — conf {Math.round(c.confidence * 100)}%
            </p>
          ))}
        </div>
      ) : null}
    </div>
  )
}
