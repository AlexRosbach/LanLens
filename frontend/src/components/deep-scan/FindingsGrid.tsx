import { useState } from 'react'
import type { DeepScanFinding } from '../../api/deepScan'
import { useI18n } from '../../i18n'

interface Props {
  findings: DeepScanFinding[]
  emptyMessage?: string
}

// ── Value helpers ──────────────────────────────────────────────────────────────

function parseJsonString(raw: string): unknown {
  const trimmed = raw.trim()
  if (!trimmed) return raw
  if (!(trimmed.startsWith('{') || trimmed.startsWith('['))) return raw
  try {
    return JSON.parse(trimmed)
  } catch {
    return raw
  }
}

function normalizeStructuredValue(raw: unknown): unknown {
  if (typeof raw === 'string') return parseJsonString(raw)
  return raw
}

function parseValue(raw: unknown): string {
  if (raw === null || raw === undefined) return '—'
  if (typeof raw === 'string') return raw
  if (typeof raw === 'number' || typeof raw === 'boolean') return String(raw)
  return JSON.stringify(raw, null, 2)
}

function asArray(raw: unknown): unknown[] {
  const normalized = normalizeStructuredValue(raw)
  if (Array.isArray(normalized)) return normalized
  if (normalized && typeof normalized === 'object') return [normalized]
  return []
}

function formatBytes(value: unknown): string | null {
  const bytes = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(bytes) || bytes <= 0) return null
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = bytes
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit += 1
  }
  const digits = size >= 100 || unit === 0 ? 0 : size >= 10 ? 1 : 2
  return `${size.toFixed(digits)} ${units[unit]}`
}

function formatCellValue(entryKey: string, value: unknown): string {
  if (Array.isArray(value)) return value.join(', ')
  if (value && typeof value === 'object') return JSON.stringify(value)
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'number' && ['Capacity', 'Size', 'TotalPhysicalMemory'].includes(entryKey)) {
    return formatBytes(value) || String(value)
  }
  return String(value)
}

function buildTableFromItems(items: Record<string, unknown>[]): { headers: string[]; rows: string[][] } | null {
  if (items.length === 0) return null
  const headerSet = new Set<string>()
  for (const item of items) {
    Object.keys(item).forEach((key) => headerSet.add(key))
  }
  const headers = Array.from(headerSet).sort((a, b) => a.localeCompare(b))
  const rows = items.map((item) => headers.map((header) => formatCellValue(header, item[header])))
  return { headers, rows }
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
  const normalizedValue = normalizeStructuredValue(finding.value)
  const raw = parseValue(normalizedValue)
  const key = finding.key

  // Already a short single-line → always show
  if (!raw.includes('\n') && raw.length < 100 && raw !== '—') return raw

  switch (key) {
    case 'cpu': {
      const line = raw.split('\n').find((l) => /model name/i.test(l))
      if (line) return line.split(':').slice(1).join(':').trim()
      break
    }
    case 'memory': {
      const line = raw.split('\n').find((l) => /^Mem:/i.test(l))
      if (line) {
        const total = line.split(/\s+/)[1]
        return total ? `${total.replace('Gi', ' GB').replace('Mi', ' MB').replace('Gib', ' GB')}` : null
      }
      break
    }
    case 'disks': {
      const lines = raw.split('\n').filter((l) => l.trim())
      const diskLines = lines.slice(1)
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
      const lines = raw.split('\n')
      const pretty = lines.find((l) => l.startsWith('PRETTY_NAME='))?.split('=').slice(1).join('=').replace(/"/g, '')
      if (pretty) return pretty
      const name = lines.find((l) => l.startsWith('NAME='))?.split('=').slice(1).join('=').replace(/"/g, '')
      const ver = lines.find((l) => l.startsWith('VERSION_ID=') || l.startsWith('VERSION='))?.split('=').slice(1).join('=').replace(/"/g, '')
      if (name && ver) return `${name} ${ver}`
      if (name) return name
      break
    }
    case 'kernel':
    case 'uptime': {
      return raw.split('\n')[0].trim() || null
    }
    case 'systemd_units': {
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
      const count = Math.max(0, lines.length - 1)
      return `${count} pod${count !== 1 ? 's' : ''}`
    }
    case 'kvm_vms':
    case 'proxmox_qemu':
    case 'proxmox_ct':
    case 'hyper_v_vms': {
      if (normalizedValue && typeof normalizedValue === 'object') {
        const items = asArray(normalizedValue).map((item) => item as Record<string, unknown>)
        const names = items
          .map((item) => (item.Name || item.name) as string | undefined)
          .filter((value): value is string => typeof value === 'string' && value.trim().length > 0)
        if (items.length > 0) return `${items.length} VM${items.length !== 1 ? 's' : ''}${names.length ? `: ${names.join(', ')}` : ''}`
      }
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
    case 'computer_system': {
      try {
        const obj = (typeof normalizedValue === 'object' ? normalizedValue : JSON.parse(raw)) as Record<string, unknown>
        const host = obj['DNSHostName'] || obj['Name']
        const model = obj['Model']
        const cpu = obj['NumberOfLogicalProcessors']
        const memory = formatBytes(obj['TotalPhysicalMemory'])
        return [host, model, cpu ? `${cpu} threads` : null, memory].filter(Boolean).join(' · ') || null
      } catch { }
      break
    }
    case 'operating_system': {
      try {
        const obj = (typeof normalizedValue === 'object' ? normalizedValue : JSON.parse(raw)) as Record<string, unknown>
        return (obj['Caption'] || obj['Name'] || obj['Version']) as string || null
      } catch { }
      break
    }
    case 'bios': {
      try {
        const obj = (typeof normalizedValue === 'object' ? normalizedValue : JSON.parse(raw)) as Record<string, unknown>
        const vendor = obj['Manufacturer']
        const version = obj['SMBIOSBIOSVersion'] || obj['Version']
        return [vendor, version].filter(Boolean).join(' · ') || null
      } catch { }
      break
    }
    case 'processor': {
      try {
        const items = asArray(normalizedValue)
        const names = items
          .map((item) => (item as Record<string, unknown>)?.Name)
          .filter((value): value is string => typeof value === 'string' && value.trim().length > 0)
        if (names.length > 0) return names.join(', ')
      } catch { }
      break
    }
    case 'physical_memory': {
      try {
        const modules = asArray(normalizedValue).map((item) => item as Record<string, unknown>)
        const total = modules.reduce((sum, module) => sum + Number(module.Capacity || 0), 0)
        const speed = modules[0]?.Speed
        const totalLabel = formatBytes(total)
        return [modules.length ? `${modules.length} module${modules.length !== 1 ? 's' : ''}` : null, totalLabel, speed ? `${speed} MHz` : null].filter(Boolean).join(' · ') || null
      } catch { }
      break
    }
    case 'disk_drives': {
      try {
        const disks = asArray(normalizedValue).map((item) => item as Record<string, unknown>)
        if (disks.length === 0) return null
        const preview = disks.slice(0, 3).map((disk) => {
          const model = typeof disk.Model === 'string' ? disk.Model : 'Disk'
          const size = formatBytes(disk.Size)
          return [model, size].filter(Boolean).join(' ')
        }).join(', ')
        return `${disks.length} disk${disks.length !== 1 ? 's' : ''}: ${preview}${disks.length > 3 ? `… +${disks.length - 3}` : ''}`
      } catch { }
      break
    }
    case 'running_services': {
      try {
        const services = asArray(normalizedValue).map((item) => item as Record<string, unknown>)
        if (services.length > 0) {
          const names = services
            .map((service) => (service.DisplayName || service.Name) as string | undefined)
            .filter((value): value is string => typeof value === 'string' && value.trim().length > 0)
          const preview = names.slice(0, 5).join(', ')
          return `${services.length} service${services.length !== 1 ? 's' : ''} running${preview ? ` — ${preview}${services.length > 5 ? `… +${services.length - 5}` : ''}` : ''}`
        }
      } catch { }
      break
    }
    case 'windows_features': {
      try {
        const features = asArray(normalizedValue)
        if (features.length > 0) return `${features.length} feature${features.length !== 1 ? 's' : ''} installed`
      } catch { }
      break
    }
    case 'licensing': {
      try {
        const items = asArray(normalizedValue).map((item) => item as Record<string, unknown>)
        const first = items[0]
        if (first) {
          const name = first.Name
          const status = Number(first.LicenseStatus)
          const statusLabel = Number.isFinite(status) ? (status === 1 ? 'Licensed' : `Status ${status}`) : null
          return [name, statusLabel].filter(Boolean).join(' · ') || null
        }
      } catch { }
      break
    }
    case 'sql_instances': {
      try {
        const items = asArray(normalizedValue).map((item) => item as Record<string, unknown>)
        if (items.length === 0) return 'No SQL instances found'
        const names = items
          .map((item) => (item.DisplayName || item.Name) as string | undefined)
          .filter((value): value is string => typeof value === 'string' && value.trim().length > 0)
        return `${items.length} SQL service${items.length !== 1 ? 's' : ''}${names.length ? ` — ${names.join(', ')}` : ''}`
      } catch { }
      break
    }
  }
  return null
}

function normalizeSource(source: string | null | undefined): string | null {
  if (!source) return null
  if (source === 'for') return null
  return source
}

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
          {expanded ? `▲ ${t('collapse')}` : `▼ ${t('expand')}`}
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

function FindingCard({ finding }: { finding: DeepScanFinding }) {
  const { t } = useI18n()
  const label = getFindingLabel(finding.key, t)
  const normalizedValue = normalizeStructuredValue(finding.value)
  const rawText = parseValue(normalizedValue)

  if (finding.key === 'computer_system' && normalizedValue && typeof normalizedValue === 'object' && !Array.isArray(normalizedValue)) {
    const obj = normalizedValue as Record<string, unknown>
    const pairs = [
      { key: 'Name', value: String(obj.DNSHostName || obj.Name || '—') },
      { key: 'Manufacturer', value: String(obj.Manufacturer || '—') },
      { key: 'Model', value: String(obj.Model || '—') },
      { key: 'System Type', value: String(obj.SystemType || '—') },
      { key: 'Logical Processors', value: String(obj.NumberOfLogicalProcessors || '—') },
      { key: 'Memory', value: formatBytes(obj.TotalPhysicalMemory) || '—' },
      { key: 'Hypervisor Present', value: String(obj.HypervisorPresent ?? '—') },
    ]
    return (
      <div className="py-3 border-b border-border last:border-0 space-y-2">
        <p className="text-xs font-semibold text-text-muted uppercase tracking-wide">{label}</p>
        <KvTable pairs={pairs} />
      </div>
    )
  }

  if (finding.key === 'bios' && normalizedValue && typeof normalizedValue === 'object' && !Array.isArray(normalizedValue)) {
    const obj = normalizedValue as Record<string, unknown>
    const biosVersion = Array.isArray(obj.BIOSVersion) ? obj.BIOSVersion.join(', ') : String(obj.BIOSVersion || '—')
    const pairs = [
      { key: 'Manufacturer', value: String(obj.Manufacturer || '—') },
      { key: 'Version', value: String(obj.SMBIOSBIOSVersion || obj.Version || '—') },
      { key: 'BIOS Version', value: biosVersion },
      { key: 'Release Date', value: String(obj.ReleaseDate || '—') },
      { key: 'SMBIOS', value: `${String(obj.SMBIOSMajorVersion ?? '—')}.${String(obj.SMBIOSMinorVersion ?? '—')}` },
    ]
    return (
      <div className="py-3 border-b border-border last:border-0 space-y-2">
        <p className="text-xs font-semibold text-text-muted uppercase tracking-wide">{label}</p>
        <KvTable pairs={pairs} />
      </div>
    )
  }

  if ((finding.key === 'processor' || finding.key === 'physical_memory' || finding.key === 'disk_drives' || finding.key === 'running_services' || finding.key === 'windows_features' || finding.key === 'sql_instances' || finding.key === 'iis_sites' || finding.key === 'hyper_v_vms' || finding.key === 'dhcp_scopes') && normalizedValue && typeof normalizedValue === 'object') {
    const items = asArray(normalizedValue).map((item) => item as Record<string, unknown>)
    const table = buildTableFromItems(items)
    if (table) {
      return (
        <div className="py-3 border-b border-border last:border-0 space-y-2">
          <p className="text-xs font-semibold text-text-muted uppercase tracking-wide">{label}</p>
          <DataTable headers={table.headers} rows={table.rows} />
        </div>
      )
    }
  }

  if (finding.key === 'licensing' && normalizedValue) {
    const items = asArray(normalizedValue).map((item) => item as Record<string, unknown>)
    if (items.length > 0) {
      const rows = items.map((item) => [String(item.Name || '—'), Number(item.LicenseStatus) === 1 ? 'Licensed' : String(item.LicenseStatus ?? '—')])
      return (
        <div className="py-3 border-b border-border last:border-0 space-y-2">
          <p className="text-xs font-semibold text-text-muted uppercase tracking-wide">{label}</p>
          <DataTable headers={['Name', 'Status']} rows={rows} />
        </div>
      )
    }
  }

  if (!rawText.includes('\n') && rawText.length < 120) {
    return (
      <div className="grid grid-cols-[minmax(160px,auto)_1fr] gap-x-4 items-start py-2 border-b border-border last:border-0">
        <span className="text-xs font-medium text-text-muted">{label}</span>
        <span className="text-xs text-text-base break-all">{rawText}</span>
      </div>
    )
  }

  const kvPairs = parseKvBlock(rawText)
  if (kvPairs) {
    return (
      <div className="py-3 border-b border-border last:border-0 space-y-2">
        <p className="text-xs font-semibold text-text-muted uppercase tracking-wide">{label}</p>
        <KvTable pairs={kvPairs} />
      </div>
    )
  }

  const rawTable = parseTable(rawText)
  if (rawTable && rawTable.rows.length > 0) {
    return (
      <div className="py-3 border-b border-border last:border-0 space-y-2">
        <p className="text-xs font-semibold text-text-muted uppercase tracking-wide">{label}</p>
        <DataTable headers={rawTable.headers} rows={rawTable.rows} />
      </div>
    )
  }

  if (normalizedValue && typeof normalizedValue === 'object') {
    const items = asArray(normalizedValue).map((item) => item as Record<string, unknown>)
    const table = buildTableFromItems(items)
    if (table) {
      return (
        <div className="py-3 border-b border-border last:border-0 space-y-2">
          <p className="text-xs font-semibold text-text-muted uppercase tracking-wide">{label}</p>
          <DataTable headers={table.headers} rows={table.rows} />
          {normalizeSource(finding.source) && (
            <span className="text-xs text-text-subtle">{t('source_label', { source: normalizeSource(finding.source) ?? '' })}</span>
          )}
        </div>
      )
    }
  }

  return (
    <div className="py-3 border-b border-border last:border-0 space-y-2">
      <p className="text-xs font-semibold text-text-muted uppercase tracking-wide">{label}</p>
      <CollapsiblePre text={rawText} />
      {normalizeSource(finding.source) && (
        <span className="text-xs text-text-subtle">{t('source_label', { source: normalizeSource(finding.source) ?? '' })}</span>
      )}
    </div>
  )
}

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

  const visibleInCompact = findings.filter((f) => extractCompact(f) !== null)
  const hiddenCount = findings.length - visibleInCompact.length

  return (
    <div>
      {expanded ? (
        <div className="divide-y divide-transparent">
          {findings.map((f) => (
            <FindingCard key={f.id} finding={f} />
          ))}
        </div>
      ) : (
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
