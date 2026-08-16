import { useQuery } from '@tanstack/react-query'
import { useInvoiceJourney } from '@/contexts/InvoiceJourneyContext'
import { apiRequest } from '@/lib/api/client'
import { SectionCard } from '@/components/journey/shared/SectionCard'

export function EvidenceComparePanel() {
  const { result } = useInvoiceJourney()
  const extraction = result.extraction
  const stage2 = result.stage2_result
  const matchedPo = stage2?.matched_pos?.[0]
  const poNumber = matchedPo?.po_number || stage2?.suggested_candidates?.[0]?.po_number

  const poQuery = useQuery({
    queryKey: ['po', poNumber],
    queryFn: () => apiRequest<Record<string, unknown>>(`/purchase-orders/${poNumber}`),
    enabled: !!poNumber,
  })

  const invoiceTotal = extraction?.total_amount?.value
  const invoiceVendor = extraction?.vendor_name?.value
  const poRef = extraction?.po_reference?.value
  const poMeta = poQuery.data?.metadata as Record<string, unknown> | undefined
  const importDerived =
    matchedPo?.import_derived === true || poMeta?.import_derived === true

  return (
    <SectionCard title="Invoice vs PO evidence" description="Side-by-side match evidence for AP review">
      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border bg-card p-4">
          <h4 className="text-sm font-semibold text-muted">On invoice</h4>
          <dl className="mt-3 space-y-2 text-sm">
            <div className="flex justify-between gap-4">
              <dt className="text-muted">Vendor</dt>
              <dd className="font-medium">{String(invoiceVendor ?? '—')}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-muted">PO reference</dt>
              <dd className="font-medium">{String(poRef ?? 'None printed')}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-muted">Total</dt>
              <dd className="font-medium">
                {invoiceTotal != null ? `$${Number(invoiceTotal).toLocaleString()}` : '—'}
              </dd>
            </div>
          </dl>
        </div>
        <div className="rounded-lg border bg-card p-4">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-sm font-semibold text-muted">In PO system</h4>
            {importDerived && (
              <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                Imported master
              </span>
            )}
            {poQuery.data && !importDerived && (
              <span className="rounded-full bg-muted/20 px-2 py-0.5 text-xs text-muted">Seed / PO master</span>
            )}
          </div>
          {poQuery.isLoading && <p className="mt-3 text-sm text-muted">Loading PO…</p>}
          {poQuery.data && (
            <dl className="mt-3 space-y-2 text-sm">
              <div className="flex justify-between gap-4">
                <dt className="text-muted">PO number</dt>
                <dd className="font-medium">{String(poQuery.data.po_number ?? poNumber)}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-muted">Vendor</dt>
                <dd className="font-medium">{String(poQuery.data.vendor_name ?? '—')}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-muted">PO total</dt>
                <dd className="font-medium">
                  ${Number(poQuery.data.total_amount ?? 0).toLocaleString()}
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-muted">Remaining</dt>
                <dd className="font-medium">
                  $
                  {(
                    Number(poQuery.data.total_amount ?? 0) -
                    Number(poQuery.data.previously_invoiced ?? 0)
                  ).toLocaleString()}
                </dd>
              </div>
            </dl>
          )}
          {!poNumber && (
            <p className="mt-3 text-sm text-muted">No PO candidate selected yet.</p>
          )}
        </div>
      </div>
    </SectionCard>
  )
}
