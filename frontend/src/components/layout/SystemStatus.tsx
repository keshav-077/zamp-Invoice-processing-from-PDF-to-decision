import { useQuery } from '@tanstack/react-query'
import { fetchHealth } from '@/lib/api/health'
import { cn } from '@/lib/utils'

export function SystemStatus() {
  const { data, isError } = useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
    refetchInterval: 30000,
    retry: 1,
  })

  const online = !isError && data?.status === 'healthy'
  const providers = data?.available_providers ?? []

  return (
    <div className="hidden items-center gap-2 sm:flex">
      <span
        className={cn(
          'h-2 w-2 rounded-full',
          online ? 'bg-success' : 'bg-danger',
        )}
      />
      <span className="text-xs text-muted">{online ? 'API online' : 'API offline'}</span>
      {providers.slice(0, 3).map((p) => (
        <span
          key={p}
          className="rounded-full border border-border px-2 py-0.5 text-[10px] uppercase tracking-wider text-muted"
        >
          {p}
        </span>
      ))}
    </div>
  )
}
