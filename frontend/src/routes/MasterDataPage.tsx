import { useMutation, useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { PageHero } from '@/components/layout/PageHero'
import { Button } from '@/components/ui/button'
import {
  confirmMasterDataImport,
  importMasterData,
  listMasterDataImports,
  previewMasterData,
  type ActivationBucket,
  type ColumnMapping,
  type MasterDataPreview,
  type SheetProfile,
} from '@/lib/api/masterData'
import { ApiError, formatApiErrorMessage } from '@/lib/api/client'

const BUCKET_LABELS: Record<string, string> = {
  vendor: 'Vendors',
  purchase_order: 'Purchase orders',
  invoice_transaction: 'Invoice transactions',
  invoice_with_po_reference: 'Invoices with PO ref',
  line: 'PO lines',
  grn: 'GRN records',
  reference: 'References',
  unclassified: 'Unclassified',
}

function MappingTable({ sheet }: { sheet: SheetProfile }) {
  const mappings = sheet.column_mappings ?? []
  if (!mappings.length) return null
  return (
    <details className="mt-3 overflow-x-auto">
      <summary className="cursor-pointer text-sm font-medium capitalize mb-2">
        {sheet.sheet} → {sheet.entity} (column mappings)
      </summary>
      <table className="w-full text-left text-xs">
        <thead>
          <tr className="text-muted">
            <th className="py-1 pr-3">Source column</th>
            <th className="py-1 pr-3">Maps to</th>
            <th className="py-1 pr-3">Confidence</th>
            <th className="py-1">Status</th>
          </tr>
        </thead>
        <tbody>
          {mappings.map((m: ColumnMapping) => (
            <tr key={m.source_column} className="border-t border-white/5">
              <td className="py-1 pr-3 font-mono">{m.source_column}</td>
              <td className="py-1 pr-3">{m.canonical_field ?? '— (metadata)'}</td>
              <td className="py-1 pr-3">{Math.round(m.confidence * 100)}%</td>
              <td className="py-1 capitalize">{m.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  )
}

function ClassificationBuckets({ summary }: { summary: Record<string, ActivationBucket> }) {
  const entries = Object.entries(summary).filter(
    ([, b]) => b.ready + b.skipped + b.review + b.blocked > 0,
  )
  if (!entries.length) return null
  return (
    <div className="space-y-2">
      <h4 className="text-sm font-medium">Classification breakdown</h4>
      <div className="grid gap-2 sm:grid-cols-2">
        {entries.map(([key, bucket]) => (
          <div key={key} className="rounded-lg bg-white/5 px-3 py-2 text-sm">
            <div className="font-medium">{BUCKET_LABELS[key] ?? key}</div>
            <div className="mt-1 text-xs text-muted space-x-2">
              <span className="text-green-400">{bucket.ready} ready</span>
              {bucket.skipped > 0 && <span>{bucket.skipped} skipped</span>}
              {bucket.review > 0 && <span className="text-yellow-400">{bucket.review} review</span>}
              {bucket.blocked > 0 && <span className="text-red-400">{bucket.blocked} blocked</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function sumBuckets(summary: Record<string, ActivationBucket> | undefined, field: keyof ActivationBucket) {
  if (!summary) return 0
  return Object.values(summary).reduce((acc, b) => acc + (b[field] ?? 0), 0)
}

function isImportComplete(preview: MasterDataPreview | null): boolean {
  return Boolean(preview?.import_id || preview?.committed)
}

function importSuccessMessage(data: MasterDataPreview): string {
  const { vendors = 0, purchase_orders: pos = 0, source_records: src = 0, po_lines: lines = 0 } =
    data.summary ?? {}
  const parts: string[] = []
  if (src > 0) parts.push(`${src} transaction(s)`)
  if (pos > 0) parts.push(`${pos} PO(s)`)
  if (vendors > 0) parts.push(`${vendors} vendor(s)`)
  if (lines > 0) parts.push(`${lines} PO line(s)`)
  const detail = parts.length > 0 ? parts.join(', ') : `${sumBuckets(data.classification_summary, 'ready')} row(s)`
  return `Master data imported — ${detail}`
}

export function MasterDataPage() {
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<MasterDataPreview | null>(null)

  const importsQuery = useQuery({
    queryKey: ['master-data-imports'],
    queryFn: () => listMasterDataImports(),
    retry: 1,
  })

  const totalReady = useMemo(
    () => sumBuckets(preview?.classification_summary, 'ready'),
    [preview],
  )
  const totalBlocked = useMemo(
    () => sumBuckets(preview?.classification_summary, 'blocked'),
    [preview],
  )

  const previewMutation = useMutation({
    mutationFn: () => previewMasterData(file!),
    onSuccess: (data) => {
      setPreview(data)
      const ready = sumBuckets(data.classification_summary, 'ready')
      if (data.valid) toast.success(`Preview ready — ${ready} row(s) activatable`)
      else if (data.review_needed) toast.message('Review column mappings before import')
      else if (data.partial_success) toast.message(`Partial preview — ${ready} row(s) ready`)
      else toast.error(`${data.errors.length} validation error(s)`)
    },
    onError: (err: Error) => {
      toast.error(formatApiErrorMessage(err, 'Preview failed — check the file format (.csv, .xlsx)'))
    },
  })

  const importMutation = useMutation({
    mutationFn: () => importMasterData(file!),
    onSuccess: (data) => {
      setPreview(data)
      if (isImportComplete(data)) {
        toast.success(importSuccessMessage(data))
      } else if (data.valid || data.partial_success) {
        toast.success('Master data imported')
      } else if (data.review_needed) {
        toast.message('Confirm mappings to complete import')
      } else {
        toast.message('Import finished — check details below')
      }
      if (data.warnings.length > 0) {
        toast.message(`${data.warnings.length} warning(s) — see details below`)
      }
      importsQuery.refetch()
    },
    onError: (err: Error) => {
      if (err instanceof ApiError && err.payload && typeof err.payload === 'object') {
        const result = err.payload as MasterDataPreview
        if (Array.isArray(result.errors) || result.row_issues) {
          setPreview(result)
          if (result.review_needed) {
            toast.message('Review column mappings, then confirm import')
            return
          }
          toast.error(
            `Import blocked: ${result.row_issues?.filter((i) => i.status === 'blocked').length ?? result.errors.length} blocking issue(s)`,
          )
          return
        }
      }
      toast.error(formatApiErrorMessage(err, 'Import failed — see details below'))
    },
  })

  const confirmMutation = useMutation({
    mutationFn: () => {
      const sheets = preview?.preview?.profile?.sheets ?? []
      return confirmMasterDataImport(file!, sheets)
    },
    onSuccess: (data) => {
      setPreview(data)
      const { vendors, purchase_orders: pos, source_records: src = 0 } = data.summary
      toast.success(
        `Import confirmed — ${pos} PO(s), ${src} transaction(s), ${vendors} vendor(s)`,
      )
      if (data.warnings.length > 0) {
        toast.message(`${data.warnings.length} warning(s) — see details below`)
      }
      importsQuery.refetch()
    },
    onError: (err: Error) => {
      if (err instanceof ApiError && err.payload && typeof err.payload === 'object') {
        const result = err.payload as MasterDataPreview
        if (Array.isArray(result.errors) || result.row_issues) {
          setPreview(result)
          toast.error(
            `Import blocked: ${result.row_issues?.filter((i) => i.status === 'blocked').length ?? result.errors.length} blocking issue(s)`,
          )
          return
        }
      }
      toast.error(formatApiErrorMessage(err, 'Import confirmation failed'))
    },
  })

  const sheets = preview?.preview?.profile?.sheets ?? []
  const unknownCount = preview?.preview?.unknown_columns?.length ?? 0
  const rowIssues = preview?.row_issues ?? []
  const attentionIssues = rowIssues.filter((i) => i.status === 'blocked' || i.status === 'review')

  const canImport = useMemo(
    () =>
      Boolean(
        preview &&
          !preview.review_needed &&
          (preview.valid || (preview.partial_success && totalBlocked === 0)),
      ),
    [preview, totalBlocked],
  )

  const canConfirm = useMemo(
    () => Boolean(preview && totalReady > 0 && totalBlocked === 0 && preview.review_needed),
    [preview, totalReady, totalBlocked],
  )

  const importComplete = isImportComplete(preview)

  return (
    <>
      <PageHero
        title="Import Master Data"
        subtitle="Upload mixed vendor, PO, and invoice/transaction data — each row is classified independently."
      />

      <div className="mx-auto max-w-4xl space-y-6">
        <div className="rounded-2xl border border-border bg-card/40 p-6">
          <p className="mb-4 text-sm text-muted">
            Supports arbitrary sheet names, flat CSV with <code className="text-accent">record_type</code>,
            and mixed files without PO numbers. Invoice rows import to source records; PO rows import to PO master.
          </p>
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null)
              setPreview(null)
            }}
            className="block w-full text-sm text-muted file:mr-4 file:rounded-full file:border-0 file:bg-white/10 file:px-4 file:py-2 file:text-sm file:text-foreground"
          />
          <div className="mt-4 flex flex-wrap gap-3">
            <Button
              variant="outline"
              disabled={!file || previewMutation.isPending}
              onClick={() => previewMutation.mutate()}
            >
              Preview
            </Button>
            <Button
              disabled={!file || !canImport || importMutation.isPending || importComplete}
              onClick={() => importMutation.mutate()}
            >
              {importComplete ? 'Imported' : importMutation.isPending ? 'Importing…' : 'Import'}
            </Button>
            {(preview?.review_needed || canConfirm) && (
              <Button
                variant="outline"
                disabled={!file || !canConfirm || confirmMutation.isPending}
                onClick={() => confirmMutation.mutate()}
              >
                Confirm mappings & import
              </Button>
            )}
          </div>
        </div>

        {preview && (
          <div
            className={`rounded-2xl border bg-card/40 p-6 space-y-4 ${
              importComplete ? 'border-green-500/40' : 'border-border'
            }`}
          >
            {importComplete && (
              <div
                role="status"
                className="rounded-xl border border-green-500/30 bg-green-500/10 px-4 py-3 text-sm text-green-300"
              >
                <p className="font-medium text-green-200">Master data imported successfully</p>
                <p className="mt-1 text-green-300/90">{importSuccessMessage(preview)}</p>
                {(preview.import_id || preview.batch_id) && (
                  <p className="mt-1 text-xs text-green-400/80">
                    {preview.import_id ? `Import ${preview.import_id}` : ''}
                    {preview.import_id && preview.batch_id ? ' · ' : ''}
                    {preview.batch_id ? `batch ${preview.batch_id}` : ''}
                  </p>
                )}
              </div>
            )}
            <h3 className="font-display text-lg">
              {importComplete
                ? 'Import complete'
                : preview.valid
                  ? 'Ready to import'
                  : preview.review_needed
                    ? 'Mapping review required'
                    : preview.partial_success
                      ? 'Partial import available'
                      : 'Validation failed'}
            </h3>
            {preview.summary.rows_analyzed != null && (
              <p className="text-sm text-muted">
                {preview.summary.rows_analyzed} row(s) analyzed
              </p>
            )}
            <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
              {['vendors', 'purchase_orders', 'source_records', 'po_lines'].map((k) => (
                <div key={k} className="rounded-lg bg-white/5 px-3 py-2">
                  <div className="text-muted capitalize">{k.replace(/_/g, ' ')}</div>
                  <div className="text-xl font-medium">{preview.summary[k] ?? 0}</div>
                </div>
              ))}
            </div>
            {preview.classification_summary && (
              <ClassificationBuckets summary={preview.classification_summary} />
            )}
            {unknownCount > 0 && (
              <p className="text-sm text-accent">
                {unknownCount} column(s) preserved as custom metadata (not dropped).
              </p>
            )}
            {attentionIssues.length > 0 && (
              <div>
                <h4 className="text-sm font-medium mb-2">Issues requiring attention</h4>
                <ul className="text-sm space-y-1 max-h-48 overflow-y-auto">
                  {attentionIssues.slice(0, 20).map((issue, idx) => (
                    <li
                      key={`${issue.row_index}-${idx}`}
                      className={issue.status === 'blocked' ? 'text-red-400' : 'text-yellow-400/90'}
                    >
                      Row {issue.row_index}: {issue.message}
                    </li>
                  ))}
                  {attentionIssues.length > 20 && (
                    <li className="text-muted">…and {attentionIssues.length - 20} more</li>
                  )}
                </ul>
              </div>
            )}
            {sheets.map((sheet) => (
              <MappingTable key={`${sheet.sheet}-${sheet.entity}`} sheet={sheet} />
            ))}
            {preview.warnings.length > 0 && (
              <ul className="text-sm text-yellow-400/90 space-y-1 max-h-40 overflow-y-auto">
                {preview.warnings.slice(0, 15).map((w) => (
                  <li key={w}>• {w}</li>
                ))}
              </ul>
            )}
            {preview.errors.length > 0 && (
              <ul className="text-sm text-red-400 space-y-1">
                {preview.errors.map((e) => (
                  <li key={e}>• {e}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        {importsQuery.data && importsQuery.data.count > 0 && (
          <div className="rounded-2xl border border-border bg-card/40 p-6">
            <h3 className="font-display text-lg mb-3">Recent imports</h3>
            <ul className="text-sm space-y-2">
              {(importsQuery.data.imports as Array<Record<string, unknown>>).slice(0, 5).map((imp) => {
                const cs = imp.classification_summary as Record<string, ActivationBucket> | undefined
                const ready = cs ? sumBuckets(cs, 'ready') : null
                return (
                  <li key={String(imp.import_id)} className="flex justify-between text-muted gap-4">
                    <span className="truncate">{String(imp.filename)}</span>
                    <span className="shrink-0">
                      {String(imp.status)}
                      {ready != null ? ` · ${ready} ready` : ''}
                      {' · '}
                      {String(imp.created_at ?? '').slice(0, 10)}
                    </span>
                  </li>
                )
              })}
            </ul>
          </div>
        )}
      </div>
    </>
  )
}
