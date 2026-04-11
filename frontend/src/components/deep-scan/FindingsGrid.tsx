import type { DeepScanFinding } from '../../api/deepScan'
import { useI18n } from '../../i18n'

interface Props {
  findings: DeepScanFinding[]
  emptyMessage?: string
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value, null, 2)
}

export default function FindingsGrid({ findings, emptyMessage }: Props) {
  const { t } = useI18n()

  if (findings.length === 0) {
    return (
      <p className="text-sm text-text-subtle py-4 text-center">
        {emptyMessage || t('deep_scan_no_findings')}
      </p>
    )
  }

  return (
    <div className="divide-y divide-border">
      {findings.map((f) => {
        const rendered = renderValue(f.value)
        const isMultiLine = rendered.includes('\n')
        return (
          <div key={f.id} className="py-3 flex flex-col gap-1">
            <div className="flex items-start justify-between gap-4">
              <span className="text-sm font-medium text-text-base min-w-[140px] shrink-0">
                {f.key}
              </span>
              {!isMultiLine && (
                <span className="text-sm text-text-muted text-right break-all">
                  {rendered}
                </span>
              )}
            </div>
            {isMultiLine && (
              <pre className="text-xs text-text-subtle bg-surface2 rounded-lg p-3 overflow-x-auto whitespace-pre-wrap break-all">
                {rendered}
              </pre>
            )}
            {f.source && (
              <span className="text-xs text-text-subtle">source: {f.source}</span>
            )}
          </div>
        )
      })}
    </div>
  )
}
