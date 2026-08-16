import { STAGE1_BADGE } from '@/lib/format'
import { Badge } from '@/components/ui/badge'

export function DecisionBadge({ status }: { status: string }) {
  const config = STAGE1_BADGE[status] ?? { label: status.toUpperCase(), variant: 'muted' as const }
  return <Badge variant={config.variant}>{config.label}</Badge>
}
