import { createContext, useContext } from 'react'
import type { PipelineResult } from '@/types'

export interface InvoiceJourneyContextValue {
  result: PipelineResult
  refresh?: () => void
}

export const InvoiceJourneyContext = createContext<InvoiceJourneyContextValue | null>(null)

export function useInvoiceJourney() {
  const ctx = useContext(InvoiceJourneyContext)
  if (!ctx) throw new Error('useInvoiceJourney must be used within InvoiceJourneyShell')
  return ctx
}
