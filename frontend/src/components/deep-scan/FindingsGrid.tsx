import { useState } from 'react'
import type { DeepScanFinding } from '../../api/deepScan'
import { useI18n } from '../../i18n'

interface Props {
  findings: DeepScanFinding[]
  emptyMessage?: string
}

// ── Value helpers ──────────────────────────────────────────────────────────────

function parseValue(raw: unknown): string {
  if (raw === null || raw === undefined) return '—'
  if (typeof raw === 'string') return raw
  if (typeof raw === 'number' || typeof raw === 'boolean') return String(raw)
  return JSON.stringify(raw, null, 2)
}

/** Try to parse a key=value or KEY=VALUE block (for example /etc/os-release) into pairs. */
function parseKvBlock(text: string): { key: string; value: string }[] | null {
  const lines = text.split('\n').map((l) => l.trim()).filter(Boolean)
  const pairs: { key: string; value: string }[] = []
  for (const line of lines) {
    const idx = line.indexOf('=')
    if (idx < 1) return null
    const k = line.slice(0, idx).trim().replace(/_/g, ' ').toLowerCase()
    const v = line.slice(idx + 1).trim().replace(/^["']|["']$/g, '')
    pairs.push({ key: k, value: v })
  }
  return pairs.length >= 3 ? pairs : null
}

/** Try to parse a column-aligned table (like lsblk, virsh list) into rows. */
function parseTable(text: string): { headers: string[]; rows: string[][] } | null {
  const lines = text.split('\n').filter((l) => l.trim())
  if (lines.length < 2) return null
  const headerLine = lines[0]
  const cols = headerLine.trim().split(/\s{2,}/).filter(Boolean)
  if (cols.length < 2) return null
  const rows = lines.slice(1).map((l) => l.trim().split(/\s{2,}/).filter(Boolean))
  if (rows.length === 0) return null
  return { headers: cols, rows }
}

// ── Compact extractors ─────────────────────────────────────────────────────────

/** Extract a one-liner summary from a finding for compact mode. Returns null = hide in compact. */
function extractCompact(finding: DeepScanFinding): string | null {
  const raw = parseValue(finding.value)
  const key = finding.key

  // Already a short single-line → always show
  if (!raw.includes('\n') && raw.length < 100 && raw !== '—') return raw

  switch (key) {
    case 'cpu': {
      // lscpu: extract "Model name" line
      const line = raw.split('\n').find((l) => /model name/i.test(l))
      if (line) return line.split(':').slice(1).join(':').trim()
      break
    }
    case 'memory': {
      // free -h: "Mem:  total  used  free …" → show total
      const line = raw.split('\n').find((l) => /^Mem:/i.test(l))
      if (line) {
        const total = line.split(/\s+/)[1]
        return total ? `${total.replace('Gi', ' GB').replace('Mi', ' MB').replace('Gib', ' GB')}` : null
      }
      break
    }
    case 'disks': {
      // lsblk: count disks and show name+size
      const lines = raw.split('\n').filter((l) => l.trim())
      const diskLines = lines.slice(1) // skip header
      if (diskLines.length > 0) {
        const parts = diskLines.map((l) => {
          const cols = l.trim().split(/\s+/)
          return cols.length >= 2 ? `${cols[0]} ${cols[1]}` : cols[0]
        })
        return `${diskLines.length} disk${diskLines.length !== 1 ? 's' : ''}: ${parts.join(', ')}`
      }
      break
    }
    case 'release': {
      // /etc/os-release: prefer PRETTY_NAME, fallback NAME + VERSION_ID
      const lines = raw.split('\n')
      const pretty = lines.find((l) => l.startsWith('PRETTY_NAME='))?.split('=').slice(1).join('=').replace(/"/g, '')
      if (pretty) return pretty
      const name = lines.find((l) => l.startsWith('NAME='))?.split('=').slice(1).join('=').replace(/"/g, '')
      const ver = lines.find((l) => l.startsWith('VERSION_ID=') || l.startsWith('VERSION='))?.split('=').slice(1).join('=').replace(/"/g, '')
      if (name && ver) return `${name} ${ver}`
      if (name) return name
      break
    }
    case 'kernel': {
      // uname -a: first line
      return raw.split('\n')[0].trim() || null
    }
    case 'uptime': {
      return raw.split('\n')[0].trim() || null
    }
    case 'systemd_units': {
      // systemctl list: count and first 8 service names
      const lines = raw.split('\n').filter((l) => l.trim())
      const names = lines.map((l) => l.trim().split(/\s+/)[0]).filter((n) => n && n.endsWith('.service'))
      if (names.length > 0) {
        const preview = names.slice(0, 8).join(', ')
        return `${names.length} services — ${preview}${names.length > 8 ? `… +${names.length - 8}` : ''}`
      }
      break
    }
    case 'docker_containers':
    case 'podman_containers': {
      const lines = raw.split('\n').filter((l) => l.trim())
      const type = key === 'docker_containers' ? 'Docker' : 'Podman'
      if (lines.length > 0) {
        const names: string[] = []
        for (const line of lines) {
          try {
            const obj = JSON.parse(line)
            const n = obj.Names || obj.Name || obj.names || ''
            if (n) names.push(n)
          } catch {
            const col = line.trim().split(/\s+/)[0]
            if (col) names.push(col)
          }
        }
        if (names.length > 0) {
          return `${names.length} ${type} container${names.length !== 1 ? 's' : ''}: ${names.join(', ')}`
        }
        return `${lines.length} ${type} containers`
      }
      break
    }
    case 'k3s_pods': {
      const lines = raw.split('\n').filter((l) => l.trim())
      const count = Math.max(0, lines.length - 1) // skip header
      return `${count} pod${count !== 1 ? 's' : ''}`
    }
    case 'kvm_vms':
    case 'proxmox_qemu':
    case 'proxmox_ct':
    case 'hyper_v_vms': {
      const table = parseTable(raw)
      if (table) {
        const count = table.rows.length
        const nameCol = table.headers.findIndex((h) => /name/i.test(h))
        if (nameCol >= 0) {
          const names = table.rows.map((r) => r[nameCol]).filter(Boolean)
          return `${count} VM${count !== 1 ? 's' : ''}: ${names.join(', ')}`
        }
        return `${count} entries`
      }
      break
    }
    case 'computer_system':
    case 'operating_system':
    case 'bios': {
      // Windows JSON objects: extract key identifying field
      try {
        const obj = typeof finding.value === 'object' ? finding.value as Record<string, unknown> : JSON.parse(raw)
        if (obj) {
          const val = obj['Caption'] || obj['Name'] || obj['Manufacturer'] || Object.values(obj)[0]
          if (val && typeof val === 'string') return val
        }
      } catch { /* ignore */ }
      break
    }
    case 'running_services': {
      const lines = raw.split('\n').filter((l) => l.trim())
      const count = Math.max(0, lines.length - 1)
      return `${count} service${count !== 1 ? 's' : ''} running`
    }
    case 'windows_features': {
      const lines = raw.split('\n').filter((l) => l.trim())
      const count = Math.max(0, lines.length - 1)
      return `${count} feature${count !== 1 ? 's' : ''} installed`
    }
  }
  return null // hide in compact mode
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function CollapsiblePre({ text, maxLines = 6 }: { text: string; maxLines?: number }) {
  const [expanded, setExpanded] = useState(false)
  const { t } = useI18n()
  const lines = text.split('\n')
  const isLong = lines.length > maxLines
  const displayed = expanded || !isLong ? text : lines.slice(0, maxLines).join('\n')

  return (
    <div>
      <pre className="text-xs text-text-subtle bg-surface rounded-lg p-3 overflow-x-auto whitespace-pre-wrap break-all border border-border">
        {displayed}
        {isLong && !expanded && '\n…'}
      </pre>
      {isLong && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-primary hover:underline mt-1"
        >
          {expanded ? t('finding_show_less') : t('finding_show_all_lines', { count: lines.length })}
        </button>
      )}
    </div>
  )
}

function KvTable({ pairs }: { pairs: { key: string; value: string }[] }) {
  return (
    <div className="grid grid-cols-[minmax(140px,auto)_1fr] gap-x-4 gap-y-1.5">
      {pairs.map((p, i) => (
        <div key={i} className="contents">
          <span className="text-xs text-text-subtle capitalize">{p.key}</span>
          <span className="text-xs text-text-base break-all">{p.value || '—'}</span>
        </div>
      ))}
    </div>
  )
}

function DataTable({ headers, rows }: { headers: string[]; rows: string[][] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-xs">
        <thead>
          <tr className="bg-surface2 border-b border-border">
            {headers.map((h, i) => (
              <th key={i} className="px-3 py-2 text-left font-medium text-text-muted">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri} className="border-b border-border last:border-0 hover:bg-surface2">
              {headers.map((_, ci) => (
                <td key={ci} className="px-3 py-1.5 text-text-base font-mono">{row[ci] ?? '—'}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Finding labels ─────────────────────────────────────────────────────────────

const KEY_LABEL_KEYS: Record<string, string> = {
  vendor: 'finding_vendor',
  model: 'finding_model',
  serial: 'finding_serial',
  cpu: 'finding_cpu',
  memory: 'finding_memory',
  disks: 'finding_disks',
  release: 'finding_release',
  kernel: 'finding_kernel',
  hostname: 'hostname',
  uptime: 'finding_uptime',
  systemd_units: 'finding_running_services',
  docker_containers: 'finding_docker_containers',
  docker_info: 'finding_docker_info',
  podman_containers: 'finding_podman_containers',
  k3s_pods: 'finding_k3s_pods',
  kvm_vms: 'finding_kvm_vms',
  proxmox_qemu: 'finding_proxmox_vms',
  proxmox_qemu_configs: 'finding_proxmox_vm_configs',
  proxmox_ct: 'finding_proxmox_containers',
  proxmox_ct_configs: 'finding_proxmox_ct_configs',
  libvirt_nets: 'finding_libvirt_networks',
  computer_system: 'finding_computer_system',
  bios: 'finding_bios',
  processor: 'finding_processor',
  physical_memory: 'finding_physical_memory',
  disk_drives: 'finding_disk_drives',
  operating_system: 'finding_operating_system',
  running_services: 'finding_running_services',
  windows_features: 'finding_windows_features',
  licensing: 'finding_licensing',
  iis_sites: 'finding_iis_sites',
  hyper_v_vms: 'finding_hyper_v_vms',
  sql_instances: 'finding_sql_instances',
  ad_domain: 'finding_ad_domain',
  dhcp_scopes: 'finding_dhcp_scopes',
}

function getFindingLabel(key: string, t: ReturnType<typeof useI18n>['t']) {
  const labelKey = KEY_LABEL_KEYS[key]
  return labelKey ? t(labelKey as Parameters<typeof t>[0]) : key.replace(/_/g, ' ')
}

// ── Full finding card (expanded mode) ─────────────────────────────────────────

function FindingCard({ finding }: { finding: DeepScanFinding }) {
  const { t } = useI18n()
  const label = getFindingLabel(finding.key, t)
  const rawText = parseValue(finding.value)

  // Short single-line values → simple row
  if (!rawText.includes('\n') && rawText.length < 120) {
    return (
      <div className="grid grid-cols-[minmax(160px,auto)_1fr] gap-x-4 items-start py-2 border-b border-border last:border-0">
        <span className="text-xs font-medium text-text-muted">{label}</span>
        <span className="text-xs text-text-base break-all">{rawText}</span>
      </div>
    )
  }

  // Try key=value block (like /etc/os-release, lscpu)
  const kvPairs = parseKvBlock(rawText)
  if (kvPairs) {
    return (
      <div className="py-3 border-b border-border last:border-0 space-y-2">
        <p className="text-xs font-semibold text-text-muted uppercase tracking-wide">{label}</p>
        <KvTable pairs={kvPairs} />
      </div>
    )
  }

  // Try column-aligned table
  const table = parseTable(rawText)
  if (table && table.rows.length > 0) {
    return (
      <div className="py-3 border-b border-border last:border-0 space-y-2">
        <p className="text-xs font-semibold text-text-muted uppercase tracking-wide">{label}</p>
        <DataTable headers={table.headers} rows={table.rows} />
      </div>
    )
  }

  // Fallback: collapsible pre block
  return (
    <div className="py-3 border-b border-border last:border-0 space-y-2">
      <p className="text-xs font-semibold text-text-muted uppercase tracking-wide">{label}</p>
      <CollapsiblePre text={rawText} />
      {finding.source && (
        <span className="text-xs text-text-subtle">{t('source_label', { source: finding.source })}</span>
      )}
    </div>
  )
}

// ── Compact row ────────────────────────────────────────────────────────────────

function CompactRow({ finding }: { finding: DeepScanFinding }) {
  const { t } = useI18n()
  const label = getFindingLabel(finding.key, t)
  const compact = extractCompact(finding)
  if (compact === null) return null
  return (
    <div className="grid grid-cols-[minmax(120px,auto)_1fr] gap-x-4 items-start py-1.5 border-b border-border last:border-0">
      <span className="text-xs font-medium text-text-muted capitalize">{label}</span>
      <span className="text-xs text-text-base break-all">{compact}</span>
    </div>
  )
}

// ── Main export ────────────────────────────────────────────────────────────────

export default function FindingsGrid({ findings, emptyMessage }: Props) {
  const { t } = useI18n()
  const [expanded, setExpanded] = useState(false)

  if (findings.length === 0) {
    return (
      <p className="text-sm text-text-subtle py-6 text-center">
        {emptyMessage || t('deep_scan_no_findings')}
      </p>
    )
  }

  // In compact mode: only show findings that have a compact representation
  const visibleInCompact = findings.filter((f) => extractCompact(f) !== null)
  const hiddenCount = findings.length - visibleInCompact.length

  return (
    <div>
      {expanded ? (
        // Expanded: show all findings in full detail
        <div className="divide-y divide-transparent">
          {findings.map((f) => (
            <FindingCard key={f.id} finding={f} />
          ))}
        </div>
      ) : (
        // Compact: show summary rows for supported findings
        <div>
          {visibleInCompact.length === 0 ? (
            <p className="text-sm text-text-subtle py-4 text-center">
              {emptyMessage || t('deep_scan_no_findings')}
            </p>
          ) : (
            <div className="divide-y divide-transparent">
              {visibleInCompact.map((f) => (
                <CompactRow key={f.id} finding={f} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Toggle */}
      <div className="flex justify-end mt-3">
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-text-subtle hover:text-primary transition-colors"
        >
          {expanded
            ? `▲ ${t('collapse')}`
            : hiddenCount > 0
              ? `▼ ${t('finding_show_all_lines', { count: findings.length })}`
              : `▼ ${t('expand')}`}
        </button>
      </div>
    </div>
  )
}
