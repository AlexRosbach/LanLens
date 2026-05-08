import { useEffect, useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import { dhcpMonitorApi, type DhcpObservation } from '../api/dhcpMonitor'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import Spinner from '../components/ui/Spinner'

function formatDate(value: string) {
  return new Date(value).toLocaleString()
}

function formatValue(value: unknown): string {
  if (Array.isArray(value)) return value.map(formatValue).join(', ')
  if (value && typeof value === 'object') return JSON.stringify(value)
  return value == null || value === '' ? '—' : String(value)
}

const HIGHLIGHT_OPTIONS = [
  ['router', 'Router / Gateway'],
  ['name_server', 'DNS'],
  ['domain', 'Domain'],
  ['domain_search', 'Search Domain'],
  ['vendor_class_id', 'Vendor Class'],
  ['client_id', 'Client ID'],
  ['server_id', 'Server ID'],
  ['lease_time', 'Lease'],
  ['renewal_time', 'Renewal'],
  ['rebinding_time', 'Rebinding'],
]

export default function DhcpMonitor() {
  const [observations, setObservations] = useState<DhcpObservation[]>([])
  const [loading, setLoading] = useState(true)
  const [capturing, setCapturing] = useState(false)
  const [expandedId, setExpandedId] = useState<number | null>(null)

  async function load() {
    const [items, status] = await Promise.all([dhcpMonitorApi.list(), dhcpMonitorApi.status()])
    setObservations(items)
    setCapturing(status.is_capturing)
  }

  useEffect(() => {
    load().finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!capturing) return
    const interval = setInterval(() => load().catch(() => {}), 3_000)
    return () => clearInterval(interval)
  }, [capturing])

  const servers = useMemo(() => {
    const map = new Map<string, number>()
    for (const obs of observations) {
      const key = obs.server_ip || obs.server_mac || 'unknown'
      map.set(key, (map.get(key) ?? 0) + 1)
    }
    return [...map.entries()]
  }, [observations])

  async function startCapture() {
    try {
      await dhcpMonitorApi.capture(20)
      setCapturing(true)
      toast.success('DHCP capture started')
      setTimeout(() => load().catch(() => {}), 2_000)
    } catch {
      toast.error('Failed to start DHCP capture')
    }
  }

  if (loading) return <div className="flex justify-center py-16"><Spinner size="lg" /></div>

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-xl font-bold text-text-base">DHCP Monitor</h1>
          <p className="text-sm text-text-subtle">
            Shows DHCP servers visible to LanLens and the options they announce. This is not a full DHCP process timeline.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {capturing && <Badge variant="warning">Capturing…</Badge>}
          <Button variant="outline" onClick={() => load().catch(() => toast.error('Refresh failed'))}>Refresh</Button>
          <Button onClick={startCapture} disabled={capturing}>{capturing ? 'Capture running' : 'Capture 20s'}</Button>
        </div>
      </div>

      <Card>
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <p className="text-xs text-text-subtle uppercase tracking-wide">Observed DHCP servers</p>
            <p className="text-2xl font-semibold text-text-base">{servers.length}</p>
          </div>
          <div>
            <p className="text-xs text-text-subtle uppercase tracking-wide">Captured replies</p>
            <p className="text-2xl font-semibold text-text-base">{observations.length}</p>
          </div>
          <div>
            <p className="text-xs text-text-subtle uppercase tracking-wide">Visibility</p>
            <p className="text-sm text-text-muted">Requires host/container packet-capture visibility for UDP 67→68.</p>
          </div>
        </div>
      </Card>

      {observations.length === 0 ? (
        <Card>
          <p className="text-sm text-text-muted">No DHCP server replies captured yet. Start a short capture while a client renews/requests a lease.</p>
        </Card>
      ) : (
        <Card className="overflow-hidden p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface2 text-text-subtle text-xs uppercase tracking-wide">
                <tr>
                  <th className="text-left px-4 py-3">Observed</th>
                  <th className="text-left px-4 py-3">DHCP Server</th>
                  <th className="text-left px-4 py-3">Type</th>
                  <th className="text-left px-4 py-3">Client</th>
                  <th className="text-left px-4 py-3">Offered IP</th>
                  <th className="text-left px-4 py-3">Key options</th>
                  <th className="text-left px-4 py-3">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {observations.map((obs) => {
                  const expanded = expandedId === obs.id
                  return (
                    <tr key={obs.id} className="align-top hover:bg-surface2/40">
                      <td className="px-4 py-3 whitespace-nowrap text-text-muted">{formatDate(obs.observed_at)}</td>
                      <td className="px-4 py-3">
                        <div className="font-medium text-text-base">{obs.server_ip || 'Unknown server'}</div>
                        <div className="text-xs text-text-subtle font-mono">{obs.server_mac || '—'}</div>
                      </td>
                      <td className="px-4 py-3"><Badge variant="primary">{obs.message_type || 'reply'}</Badge></td>
                      <td className="px-4 py-3">
                        <div className="text-text-muted">{obs.client_hostname || '—'}</div>
                        <div className="text-xs text-text-subtle font-mono">{obs.client_mac || '—'}</div>
                      </td>
                      <td className="px-4 py-3 text-text-muted font-mono">{obs.offered_ip || obs.requested_ip || '—'}</td>
                      <td className="px-4 py-3 min-w-72">
                        <div className="flex flex-wrap gap-1.5">
                          {HIGHLIGHT_OPTIONS.map(([key, label]) => (
                            obs.options[key] != null ? (
                              <span key={key} className="rounded-md bg-surface2 px-2 py-1 text-xs text-text-muted">
                                <span className="text-text-subtle">{label}:</span> {formatValue(obs.options[key])}
                              </span>
                            ) : null
                          ))}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <button className="text-primary hover:text-primary/80 text-xs font-medium" onClick={() => setExpandedId(expanded ? null : obs.id)}>
                          {expanded ? 'Hide options' : 'Show options'}
                        </button>
                        {expanded && (
                          <pre className="mt-2 max-w-lg overflow-auto rounded-lg bg-background p-3 text-xs text-text-muted border border-border">
                            {JSON.stringify(obs.options, null, 2)}
                          </pre>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  )
}
