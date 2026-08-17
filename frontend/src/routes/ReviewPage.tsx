import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { PageHero } from '@/components/layout/PageHero'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input, Label, Select, Textarea } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { fetchExceptionAnalytics, fetchReviews, submitReviewAction } from '@/lib/api/reviews'
import { Link } from 'react-router-dom'
import { formatApiErrorMessage } from '@/lib/api/client'

const ACTIONS = ['APPROVE', 'REJECT', 'COMMENT', 'OVERRIDE']

export function ReviewPage() {
  const queryClient = useQueryClient()
  const reviewsQuery = useQuery({ queryKey: ['reviews'], queryFn: () => fetchReviews({ limit: 50 }) })
  const analyticsQuery = useQuery({ queryKey: ['analytics'], queryFn: fetchExceptionAnalytics })

  return (
    <>
      <PageHero title="Review Queue" subtitle="Human review work items and exception analytics." />

      {analyticsQuery.data && (
        <div className="mb-10 grid gap-4 sm:grid-cols-3">
          <Card className="p-6">
            <p className="text-2xl font-semibold">{analyticsQuery.data.auto_pass_rate}%</p>
            <p className="text-sm text-muted">Auto-pass rate</p>
          </Card>
          <Card className="p-6">
            <p className="text-2xl font-semibold">
              {analyticsQuery.data.po_suggestion_acceptance_rate}%
            </p>
            <p className="text-sm text-muted">PO accept rate</p>
          </Card>
          <Card className="p-6">
            <p className="text-2xl font-semibold">{analyticsQuery.data.residual_review_count}</p>
            <p className="text-sm text-muted">Residual reviews</p>
          </Card>
        </div>
      )}

      {reviewsQuery.isLoading ? (
        <Skeleton className="h-60" />
      ) : !reviewsQuery.data?.work_items?.length ? (
        <p className="text-sm text-muted">No open review items.</p>
      ) : (
        <div className="space-y-6">
          {reviewsQuery.data.work_items.map((item) => (
            <ReviewItemCard
              key={item.work_item_id}
              item={item}
              onSubmitted={() => {
                queryClient.invalidateQueries({ queryKey: ['reviews'] })
                queryClient.invalidateQueries({ queryKey: ['invoices'] })
              }}
            />
          ))}
        </div>
      )}
    </>
  )
}

function ReviewItemCard({
  item,
  onSubmitted,
}: {
  item: {
    work_item_id: string
    document_id: string
    queue: string
    reason_codes?: string[]
    priority: string
    sla_due_at?: string
  }
  onSubmitted: () => void
}) {
  const [actionType, setActionType] = useState('APPROVE')
  const [actor, setActor] = useState('reviewer')
  const [detail, setDetail] = useState('')

  const mutation = useMutation({
    mutationFn: () =>
      submitReviewAction(item.document_id, {
        action_type: actionType,
        actor_id: actor,
        detail,
        outcome: actionType,
      }),
    onSuccess: () => {
      toast.success('Review action recorded')
      onSubmitted()
    },
    onError: (e: Error) => {
      toast.error(formatApiErrorMessage(e, 'Review action failed'))
    },
  })

  return (
    <Card className="space-y-4 p-6">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium">
            {item.work_item_id} · {item.queue}
          </p>
          <Link to={`/invoice/${item.document_id}/stage/1`} className="text-sm text-accent hover:underline">
            {item.document_id}
          </Link>
        </div>
        <p className="text-xs text-muted">
          {item.priority}
          {item.sla_due_at ? ` · SLA ${item.sla_due_at.slice(0, 19)}` : ''}
        </p>
      </div>

      {item.reason_codes?.length ? (
        <p className="text-sm text-muted">Reasons: {item.reason_codes.join(', ')}</p>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <Label>Action</Label>
          <Select value={actionType} onChange={(e) => setActionType(e.target.value)}>
            {ACTIONS.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </Select>
        </div>
        <div className="space-y-2">
          <Label>Actor ID</Label>
          <Input value={actor} onChange={(e) => setActor(e.target.value)} />
        </div>
      </div>
      <div className="space-y-2">
        <Label>Detail</Label>
        <Textarea value={detail} onChange={(e) => setDetail(e.target.value)} />
      </div>
      <Button onClick={() => mutation.mutate()} disabled={mutation.isPending}>
        Submit action
      </Button>
    </Card>
  )
}
