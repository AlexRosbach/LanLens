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

/** Try to parse a key=value or KEY=VALUE block (like /etc/os-release, lscpu) into pairs. */
function parseKvBlock(text: string): { key: string; value: string }[] | null {
  const lines = text.split('\n').map((l) => l.trim()).filter(Boolean)
  const pairs: { key: string; value: string }[] = []
  for (const line of lines) {
    const idx = line.indexOf('=')
    if (idx < 1) return null  // not a kv block
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
  // Heuristic: header line contains only uppercase/short words, separator line has dashes
  const headerLine = lines[0]
  const cols = headerLine.trim().split(/\s{2,}/).filter(Boolean)
  if (cols.length < 2) return null
  const rows = lines.slice(1).map((l) => l.trim().split(/\s{2,}/).filter(Boolean))
  if (rows.length === 0) return null
  return { headers: cols, rows }
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function CollapsiblePre({ text, maxLines = 8 }: { text: string; maxLines?: number }) {
  const [expanded, setExpanded] = useState(false)
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
          {expanded ? 'Show less ▲' : `Show all ${lines.length} lines ▼`}
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

const KEY_LABELS: Record<string, string> = {
  vendor: 'Vendor',
  model: 'Model',
  serial: 'Serial',
  cpu: 'CPU',
  memory: 'Memory',
  disks: 'Disks',
  release: 'OS Release',
  kernel: 'Kernel',
  hostname: 'Hostname',
  uptime: 'Uptime',
  systemd_units: 'Running Services',
  docker_containers: 'Docker Containers',
  docker_info: 'Docker Info',
  podman_containers: 'Podman Containers',
  k3s_pods: 'k3s Pods',
  kvm_vms: 'KVM VMs',
  proxmox_qemu: 'Proxmox VMs',
  proxmox_qemu_configs: 'Proxmox VM Configs',
  proxmox_ct: 'Proxmox Containers',
  proxmox_ct_configs: 'Proxmox CT Configs',
  libvirt_nets: 'libvirt Networks',
  computer_system: 'Computer System',
  bios: 'BIOS',
  processor: 'Processor',
  physical_memory: 'Physical Memory',
  disk_drives: 'Disk Drives',
  operating_system: 'Operating System',
  running_services: 'Running Services',
  windows_features: 'Windows Features',
  licensing: 'Licensing',
  iis_sites: 'IIS Sites',
  hyper_v_vms: 'Hyper-V VMs',
  sql_instances: 'SQL Instances',
  ad_domain: 'Active Directory Domain',
  dhcp_scopes: 'DHCP Scopes',
}

// ── Finding card ───────────────────────────────────────────────────────────────

function FindingCard({ finding }: { finding: DeepScanFinding }) {
  const label = KEY_LABELS[finding.key] ?? finding.key.replace(/_/g, ' ')
  const rawText = parseValue(finding.value)

  // Short single-line values → simple row
  if (!rawText.includes('\n') && rawText.length < 120) {
    return (
      <div className="grid grid-cols-[minmax(160px,auto)_1fr] gap-x-4 gap-y-0 items-start py-2 border-b border-border last:border-0">
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
        <span className="text-xs text-text-subtle">source: {finding.source}</span>
      )}
    </div>
  )
}

// ── Main export ────────────────────────────────────────────────────────────────

export default function FindingsGrid({ findings, emptyMessage }: Props) {
  const { t } = useI18n()

  if (findings.length === 0) {
    return (
      <p className="text-sm text-text-subtle py-6 text-center">
        {emptyMessage || t('deep_scan_no_findings')}
      </p>
    )
  }

  return (
    <div className="divide-y divide-transparent">
      {findings.map((f) => (
        <FindingCard key={f.id} finding={f} />
      ))}
    </div>
  )
}
