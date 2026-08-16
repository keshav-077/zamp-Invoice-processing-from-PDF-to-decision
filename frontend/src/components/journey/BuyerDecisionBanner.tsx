import { mapBuyerVerdict } from '@/lib/buyerVerdict'
import { useInvoiceJourney } from '@/contexts/InvoiceJourneyContext'
import { cn } from '@/lib/utils'

const styles = {
  pay: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-800',
  do_not_pay: 'border-red-500/40 bg-red-500/10 text-red-800',
  needs_review: 'border-amber-500/40 bg-amber-500/10 text-amber-900',
  pending: 'border-slate-300 bg-slate-50 text-slate-700',
}

export function BuyerDecisionBanner() {
  const { result } = useInvoiceJourney()
  const { verdict, headline, reason, detail } = mapBuyerVerdict(result)

  return (
    <div
      className={cn(
        'mb-6 rounded-xl border-2 px-6 py-4',
        styles[verdict],
      )}
      data-testid="buyer-decision-banner"
    >
      <p className="text-xs font-semibold uppercase tracking-wide opacity-70">Buyer verdict</p>
      <p className="mt-1 text-2xl font-bold">{headline}</p>
      <p className="mt-2 text-sm opacity-90">{reason}</p>
      {detail && (
        <p className="mt-1 text-xs opacity-80 line-clamp-3" title={detail}>
          {detail}
        </p>
      )}
    </div>
  )
}
