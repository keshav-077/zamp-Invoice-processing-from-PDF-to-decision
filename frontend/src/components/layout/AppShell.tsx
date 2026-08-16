import { StickyHeader } from './StickyHeader'

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-background">
      <StickyHeader />
      <main className="mx-auto max-w-6xl px-4 py-10 md:px-6 md:py-14">{children}</main>
      <footer className="border-t border-border py-8 text-center text-xs text-muted">
        InvoiceFlow AI v1.0 — Stages 1–5 Pipeline
      </footer>
    </div>
  )
}
