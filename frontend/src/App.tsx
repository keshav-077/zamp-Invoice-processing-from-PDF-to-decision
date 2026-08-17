import { BrowserRouter, Navigate, Route, Routes, useLocation, useParams } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'sonner'
import { AppShell } from '@/components/layout/AppShell'
import { UploadPage } from '@/routes/UploadPage'
import { DashboardPage } from '@/routes/DashboardPage'
import { HistoryPage } from '@/routes/HistoryPage'
import { MasterDataPage } from '@/routes/MasterDataPage'
import { ReviewPage } from '@/routes/ReviewPage'
import { InvoiceJourneyRedirect, InvoiceJourneyShell } from '@/routes/InvoiceJourneyPage'
import type { PipelineResult } from '@/types'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 10000, retry: 1 },
  },
})

function JourneyWithState() {
  const location = useLocation()
  const state = location.state as { result?: PipelineResult } | null
  return <InvoiceJourneyShell initialResult={state?.result} />
}

function HistoryRedirect() {
  const { documentId } = useParams()
  return <Navigate to={`/invoice/${documentId}/stage/1`} replace />
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppShell>
          <Routes>
            <Route path="/" element={<UploadPage />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/history/:documentId" element={<HistoryRedirect />} />
            <Route path="/invoice/:documentId" element={<InvoiceJourneyRedirect />} />
            <Route path="/invoice/:documentId/stage/:stageNum" element={<JourneyWithState />} />
            <Route path="/master-data" element={<MasterDataPage />} />
            <Route path="/review" element={<ReviewPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AppShell>
      </BrowserRouter>
      <Toaster
        theme="dark"
        position="top-right"
        richColors
        toastOptions={{
          classNames: {
            toast: 'border border-border bg-surface text-foreground',
            title: 'text-foreground',
            description: 'text-muted',
            error: 'border-danger/40 bg-danger/15 text-foreground',
            success: 'border-success/40 bg-success/15 text-foreground',
          },
        }}
      />
    </QueryClientProvider>
  )
}
