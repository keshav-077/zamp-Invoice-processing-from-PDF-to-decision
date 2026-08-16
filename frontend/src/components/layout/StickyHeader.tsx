import { Link, useLocation } from 'react-router-dom'
import { Menu, X, Receipt } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/utils'
import { SystemStatus } from './SystemStatus'

const NAV = [
  { to: '/', label: 'Upload' },
  { to: '/master-data', label: 'Master Data Import' },
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/history', label: 'History' },
  { to: '/review', label: 'Review' },
]

export function StickyHeader() {
  const location = useLocation()
  const [open, setOpen] = useState(false)

  return (
    <header className="sticky top-0 z-50 border-b border-border bg-background/90 backdrop-blur-md">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-4 md:px-6">
        <Link to="/" className="flex items-center gap-2">
          <Receipt className="h-5 w-5 text-accent" strokeWidth={1.5} />
          <span className="font-display text-xl tracking-tight">InvoiceFlow</span>
        </Link>

        <nav className="hidden items-center gap-1 md:flex">
          {NAV.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className={cn(
                'rounded-full px-4 py-2 text-sm transition-colors',
                location.pathname === item.to || (item.to !== '/' && location.pathname.startsWith(item.to))
                  ? 'bg-white/10 text-foreground'
                  : 'text-muted hover:text-foreground',
              )}
            >
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="flex items-center gap-3">
          <SystemStatus />
          <button
            type="button"
            className="rounded-full p-2 text-muted hover:bg-white/5 md:hidden"
            onClick={() => setOpen(!open)}
            aria-label="Toggle menu"
          >
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>

      {open && (
        <nav className="border-t border-border px-4 py-3 md:hidden">
          {NAV.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              onClick={() => setOpen(false)}
              className={cn(
                'block rounded-xl px-3 py-2 text-sm',
                location.pathname === item.to ? 'bg-white/10' : 'text-muted',
              )}
            >
              {item.label}
            </Link>
          ))}
        </nav>
      )}
    </header>
  )
}
