import type { InvoiceExtraction } from '@/types'
import { formatCurrency } from '@/lib/format'
import { ConfidenceBar } from './ConfidenceBar'

export function LineItemsTable({ extraction }: { extraction: InvoiceExtraction | null | undefined }) {
  const items = extraction?.line_items ?? []
  if (!items.length) {
    return <p className="text-sm text-muted">No line items extracted.</p>
  }

  const currency = extraction?.currency?.value ?? 'USD'

  return (
    <div className="overflow-x-auto rounded-2xl border border-border">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-muted">
            <th className="px-4 py-3 font-medium">#</th>
            <th className="px-4 py-3 font-medium">Description</th>
            <th className="px-4 py-3 font-medium">Qty</th>
            <th className="px-4 py-3 font-medium">Unit</th>
            <th className="px-4 py-3 font-medium">Amount</th>
            <th className="px-4 py-3 font-medium">Conf.</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, i) => (
            <tr key={i} className="border-b border-border/50 hover:bg-white/[0.02]">
              <td className="px-4 py-3">{item.line_number ?? i + 1}</td>
              <td className="px-4 py-3">{item.description}</td>
              <td className="px-4 py-3">{item.quantity ?? '—'}</td>
              <td className="px-4 py-3">
                {item.unit_price != null ? formatCurrency(item.unit_price, String(currency)) : '—'}
              </td>
              <td className="px-4 py-3">
                {item.amount != null ? formatCurrency(item.amount, String(currency)) : '—'}
              </td>
              <td className="px-4 py-3">
                <ConfidenceBar confidence={item.confidence} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
