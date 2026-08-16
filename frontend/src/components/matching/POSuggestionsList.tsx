import type { Stage2Result } from '@/types'
import { coalesceDict, scoreTotal } from '@/lib/normalize'
import { num } from '@/lib/normalize'
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { confirmPo, rejectPoSuggestions } from '@/lib/api/invoices'
import { Button } from '@/components/ui/button'
import { Input, Label, Select, Textarea } from '@/components/ui/input'
import { Card } from '@/components/ui/card'

interface Props {
  documentId: string
  stage2: Stage2Result | null | undefined
  interactive?: boolean
}

export function POSuggestionsList({ documentId, stage2, interactive = true }: Props) {
  const data = coalesceDict(stage2)
  const candidates = data.suggested_candidates ?? data.matched_pos ?? []
  const [poChoice, setPoChoice] = useState(candidates[0]?.po_number ?? '')
  const [reviewer, setReviewer] = useState('reviewer')
  const [notes, setNotes] = useState('')
  const queryClient = useQueryClient()

  const confirmMutation = useMutation({
    mutationFn: () => confirmPo(documentId, { po_number: poChoice, confirmed_by: reviewer, notes }),
    onSuccess: () => {
      toast.success(`PO ${poChoice} confirmed`)
      queryClient.invalidateQueries({ queryKey: ['invoice', documentId] })
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const rejectMutation = useMutation({
    mutationFn: () => rejectPoSuggestions(documentId, { rejected_by: reviewer, notes }),
    onSuccess: () => {
      toast.warning('PO suggestions rejected')
      queryClient.invalidateQueries({ queryKey: ['invoice', documentId] })
    },
    onError: (e: Error) => toast.error(e.message),
  })

  if (!candidates.length) return null

  return (
    <div className="space-y-4">
      <h4 className="text-base font-medium">PO Suggestions</h4>
      {data.po_presence === 'non_po' && (
        <p className="text-xs text-muted">
          No PO on invoice — similar POs shown by vendor/amount heuristics.
        </p>
      )}

      <div className="space-y-2">
        {candidates.slice(0, 5).map((cand, i) => {
          const score = cand.score ?? {}
          const total = scoreTotal(score as Record<string, unknown>)
          return (
            <Card key={cand.po_number} className="p-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="font-medium">
                    #{i + 1} {cand.po_number} — {cand.vendor_name ?? '?'}
                  </p>
                  <p className="text-xs text-muted">Score {total.toFixed(0)} · {cand.po_status ?? '?'}</p>
                </div>
                {typeof score === 'object' && score && (
                  <p className="text-xs text-muted">
                    PO {num(score.po_match)} | Vendor {num(score.vendor_match)} | Lines{' '}
                    {num(score.line_match)} | Amount {num(score.amount_match)}
                  </p>
                )}
              </div>
              {cand.evidence?.slice(0, 3).map((ev, j) => (
                <p key={j} className="mt-1 text-xs text-muted">
                  • {ev}
                </p>
              ))}
            </Card>
          )
        })}
      </div>

      {!interactive && documentId && (
        <p className="text-xs text-muted">Use the PO Confirm tab to confirm or reject a match.</p>
      )}

      {interactive && documentId && (
        <Card className="space-y-4 p-4">
          <div className="space-y-2">
            <Label htmlFor="po-select">Confirm PO match</Label>
            <Select
              id="po-select"
              value={poChoice}
              onChange={(e) => setPoChoice(e.target.value)}
            >
              {candidates.map((c) => (
                <option key={c.po_number} value={c.po_number}>
                  {c.po_number}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="reviewer">Your name / ID</Label>
            <Input id="reviewer" value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="notes">Notes</Label>
            <Textarea id="notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>
          <div className="flex flex-wrap gap-3">
            <Button
              onClick={() => confirmMutation.mutate()}
              disabled={confirmMutation.isPending || !poChoice}
            >
              Confirm match
            </Button>
            <Button
              variant="outline"
              onClick={() => rejectMutation.mutate()}
              disabled={rejectMutation.isPending}
            >
              None of these
            </Button>
          </div>
        </Card>
      )}
    </div>
  )
}
