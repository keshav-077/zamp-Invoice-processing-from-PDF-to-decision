import { cn } from '@/lib/utils'

export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        'flex h-10 w-full rounded-xl border border-border bg-surface-elevated px-3 py-2 text-sm text-foreground placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-white/10',
        className,
      )}
      {...props}
    />
  )
}

export function Textarea({ className, ...props }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        'flex min-h-[80px] w-full rounded-xl border border-border bg-surface-elevated px-3 py-2 text-sm text-foreground placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-white/10',
        className,
      )}
      {...props}
    />
  )
}

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn('text-sm font-medium text-muted', className)} {...props} />
}

export function Select({
  className,
  ...props
}: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        'flex h-10 w-full rounded-xl border border-border bg-surface-elevated px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-white/10',
        className,
      )}
      {...props}
    />
  )
}
