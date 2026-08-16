import { STAGE2_BADGE } from '@/lib/format'
import { Badge } from '@/components/ui/badge'

export function Stage2Badge({ status }: { status: string }) {
  const label = STAGE2_BADGE[status] ?? status.replace(/_/g, ' ').toUpperCase()
  return <Badge variant="warning">{label}</Badge>
}
