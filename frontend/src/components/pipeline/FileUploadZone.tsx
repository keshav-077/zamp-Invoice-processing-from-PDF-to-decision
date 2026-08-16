import { useCallback, useState } from 'react'
import { Upload } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

const ACCEPT = ['application/pdf', 'image/png', 'image/jpeg', 'image/jpg']
const MAX_MB = 50

interface FileUploadZoneProps {
  file: File | null
  onFileSelect: (file: File | null) => void
  disabled?: boolean
}

export function FileUploadZone({ file, onFileSelect, disabled }: FileUploadZoneProps) {
  const [dragOver, setDragOver] = useState(false)

  const validate = useCallback((f: File) => {
    if (f.size > MAX_MB * 1024 * 1024) {
      return `File exceeds ${MAX_MB}MB limit`
    }
    const ext = f.name.split('.').pop()?.toLowerCase()
    if (!['pdf', 'png', 'jpg', 'jpeg'].includes(ext ?? '')) {
      return 'Unsupported file type'
    }
    return null
  }, [])

  const handleFile = (f: File | null) => {
    if (!f) {
      onFileSelect(null)
      return
    }
    const err = validate(f)
    if (err) {
      alert(err)
      return
    }
    onFileSelect(f)
  }

  return (
    <div
      className={cn(
        'rounded-2xl border border-dashed border-border bg-surface p-10 text-center transition-colors',
        dragOver && 'border-accent/50 bg-white/[0.02]',
        disabled && 'opacity-50',
      )}
      onDragOver={(e) => {
        e.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragOver(false)
        handleFile(e.dataTransfer.files[0] ?? null)
      }}
    >
      <Upload className="mx-auto mb-4 h-8 w-8 text-muted" strokeWidth={1.5} />
      <p className="mb-2 text-sm">Drop your invoice here</p>
      <p className="mb-4 text-xs text-muted">PDF, PNG, JPG — max {MAX_MB}MB</p>
      <label>
        <Button variant="outline" size="sm" disabled={disabled} asChild>
          <span>Browse files</span>
        </Button>
        <input
          type="file"
          className="hidden"
          accept={ACCEPT.join(',')}
          disabled={disabled}
          onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
        />
      </label>
      {file && (
        <div className="mt-6 rounded-xl border border-border bg-surface-elevated p-4 text-left text-sm">
          <p className="font-medium">{file.name}</p>
          <p className="text-muted">{(file.size / 1024).toFixed(1)} KB · {file.type || 'unknown'}</p>
          <Button
            variant="ghost"
            size="sm"
            className="mt-2"
            onClick={() => onFileSelect(null)}
            disabled={disabled}
          >
            Remove
          </Button>
        </div>
      )}
    </div>
  )
}
