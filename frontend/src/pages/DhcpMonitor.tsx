import { useEffect, useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import { dhcpMonitorApi, type DhcpObservation } from '../api/dhcpMonitor'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import Spinner from '../components/ui/Spinner'
import { useI18n } from '../i18n'

function formatDate(value: string) {
  return new Date(value).toLocaleString()
}

function formatValue(value: unknown): string {
  if (Array.isArray(value)) return value.map(formatValue).join(', ')
  if (value && typeof value === 'object') return JSON.stringify(value)
  return value == null || value === '' ? '—' : String(value)
}

const HIGHLIGHT_OPTIONS = [
  ['router', 'dhcp_option_router'],
  ['name_server', 'dhcp_option_dns'],
  ['domain', 'dhcp_option_domain'],
  ['domain_search', 'dhcp_option_search_domain'],
  ['vendor_class_id', 'dhcp_option_vendor_class'],
  ['client_id', 'dhcp_option_client_id'],
  ['server_id', 'dhcp_option_server_id'],
  ['lease_time', 'dhcp_option_lease'],
  ['renewal_time', 'dhcp_option_renewal'],
  ['rebinding_time', 'dhcp_option_rebinding'],
] as const

export default function DhcpMonitor() {
  const { t } = useI18n()
  const [observations, setObservations] = useState<DhcpObservation[]>([])
  const [loading, setLoading] = useState(true)
  const [capturing, setCapturing] = useState(false)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [loadError, setLoadError] = useState(false)

  async function load() {
    const [items, status] = await Promise.all([dhcpMonitorApi.list(), dhcpMonitorApi.status()])
    setObservations(items)
    setCapturing(status.is_capturing)
    setLoadError(false)
  }

  useEffect(() => {
    load()
      .catch(() => {
        setLoadError(true)
        toast.error(t('dhcp_load_failed'))
      })
      .finally(() => setLoading(false))
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
      const result = await dhcpMonitorApi.capture(20)
      if (!result.success) {
        toast.error(result.message || t('dhcp_capture_already_running'))
        await load().catch(() => {})
        return
      }
      setCapturing(true)
      toast.success(t('dhcp_capture_started'))
      setTimeout(() => load().catch(() => {}), 2_000)
    } catch {
      toast.error(t('dhcp_capture_failed'))
    }
  }

  if (loading) return <div className="flex justify-center py-16"><Spinner size="lg" /></div>

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-xl font-bold text-text-base">{t('nav_dhcp_monitor')}</h1>
          <p className="text-sm text-text-subtle">
            {t('dhcp_monitor_description')}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {capturing && <Badge variant="warning">{t('dhcp_capturing')}</Badge>}
          <Button variant="outline" onClick={() => load().catch(() => toast.error(t('dhcp_refresh_failed')))}>{t('refresh')}</Button>
          <Button onClick={startCapture} disabled={capturing}>{capturing ? t('dhcp_capture_running') : t('dhcp_capture_20s')}</Button>
        </div>
      </div>

      {loadError && (
        <Card>
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <p className="text-sm text-danger">{t('dhcp_load_failed')}</p>
            <Button variant="outline" onClick={() => load().catch(() => toast.error(t('dhcp_refresh_failed')))}>{t('retry')}</Button>
          </div>
        </Card>
      )}

      <Card>
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <p className="text-xs text-text-subtle uppercase tracking-wide">{t('dhcp_observed_servers')}</p>
            <p className="text-2xl font-semibold text-text-base">{servers.length}</p>
          </div>
          <div>
            <p className="text-xs text-text-subtle uppercase tracking-wide">{t('dhcp_captured_replies')}</p>
            <p className="text-2xl font-semibold text-text-base">{observations.length}</p>
          </div>
          <div>
            <p className="text-xs text-text-subtle uppercase tracking-wide">{t('dhcp_visibility')}</p>
            <p className="text-sm text-text-muted">{t('dhcp_visibility_hint')}</p>
          </div>
        </div>
      </Card>

      {observations.length === 0 ? (
        <Card>
          <p className="text-sm text-text-muted">{t('dhcp_empty')}</p>
        </Card>
      ) : (
        <Card className="overflow-hidden p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface2 text-text-subtle text-xs uppercase tracking-wide">
                <tr>
                  <th className="text-left px-4 py-3">{t('dhcp_observed')}</th>
                  <th className="text-left px-4 py-3">{t('dhcp_server')}</th>
                  <th className="text-left px-4 py-3">{t('type')}</th>
                  <th className="text-left px-4 py-3">{t('dhcp_client')}</th>
                  <th className="text-left px-4 py-3">{t('dhcp_offered_ip')}</th>
                  <th className="text-left px-4 py-3">{t('dhcp_key_options')}</th>
                  <th className="text-left px-4 py-3">{t('details')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {observations.map((obs) => {
                  const expanded = expandedId === obs.id
                  return (
                    <tr key={obs.id} className="align-top hover:bg-surface2/40">
                      <td className="px-4 py-3 whitespace-nowrap text-text-muted">{formatDate(obs.observed_at)}</td>
                      <td className="px-4 py-3">
                        <div className="font-medium text-text-base">{obs.server_ip || t('dhcp_unknown_server')}</div>
                        <div className="text-xs text-text-subtle font-mono">{obs.server_mac || '—'}</div>
                      </td>
                      <td className="px-4 py-3"><Badge variant="primary">{obs.message_type || t('dhcp_reply')}</Badge></td>
                      <td className="px-4 py-3">
                        <div className="text-text-muted">{obs.client_hostname || '—'}</div>
                        <div className="text-xs text-text-subtle font-mono">{obs.client_mac || '—'}</div>
                      </td>
                      <td className="px-4 py-3 text-text-muted font-mono">{obs.offered_ip || obs.requested_ip || '—'}</td>
                      <td className="px-4 py-3 min-w-72">
                        <div className="flex flex-wrap gap-1.5">
                          {HIGHLIGHT_OPTIONS.map(([key, labelKey]) => (
                            obs.options[key] != null ? (
                              <span key={key} className="rounded-md bg-surface2 px-2 py-1 text-xs text-text-muted">
                                <span className="text-text-subtle">{t(labelKey)}:</span> {formatValue(obs.options[key])}
                              </span>
                            ) : null
                          ))}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <button className="text-primary hover:text-primary/80 text-xs font-medium" onClick={() => setExpandedId(expanded ? null : obs.id)}>
                          {expanded ? t('dhcp_hide_options') : t('dhcp_show_options') }
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
