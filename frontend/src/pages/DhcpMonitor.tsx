import { useEffect, useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import { dhcpMonitorApi, type DhcpAuthorizedServer, type DhcpObservation } from '../api/dhcpMonitor'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import Input from '../components/ui/Input'
import Spinner from '../components/ui/Spinner'
import { useI18n } from '../i18n'
import { useUiSettingsStore } from '../store/uiSettingsStore'
import { parseDateStr } from '../utils/formatters'

function formatDate(value: string) {
  try {
    return parseDateStr(value).toLocaleString()
  } catch {
    return value
  }
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
  const advancedViewEnabled = useUiSettingsStore((state) => state.advancedViewEnabled)
  const uiSettingsLoading = useUiSettingsStore((state) => state.loading)
  const fetchUiSettings = useUiSettingsStore((state) => state.fetchUiSettings)
  const [observations, setObservations] = useState<DhcpObservation[]>([])
  const [authorizedServers, setAuthorizedServers] = useState<DhcpAuthorizedServer[]>([])
  const [loading, setLoading] = useState(true)
  const [uiSettingsChecked, setUiSettingsChecked] = useState(false)
  const [capturing, setCapturing] = useState(false)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [loadError, setLoadError] = useState(false)
  const [allowlistName, setAllowlistName] = useState('')
  const [allowlistIp, setAllowlistIp] = useState('')
  const [allowlistMac, setAllowlistMac] = useState('')
  const [allowlistSaving, setAllowlistSaving] = useState(false)

  async function load() {
    const [items, status, allowlist] = await Promise.all([
      dhcpMonitorApi.list(),
      dhcpMonitorApi.status(),
      dhcpMonitorApi.authorizedServers(),
    ])
    setObservations(items)
    setCapturing(status.is_capturing)
    setAuthorizedServers(allowlist)
    setLoadError(false)
  }

  useEffect(() => {
    fetchUiSettings().finally(() => setUiSettingsChecked(true))
  }, [fetchUiSettings])

  useEffect(() => {
    if (!uiSettingsChecked) return
    if (advancedViewEnabled) {
      load()
        .catch(() => {
          setLoadError(true)
          toast.error(t('dhcp_load_failed'))
        })
        .finally(() => setLoading(false))
    } else if (!uiSettingsLoading) {
      setLoading(false)
    }
  }, [advancedViewEnabled, uiSettingsChecked, uiSettingsLoading])

  useEffect(() => {
    if (!capturing) return
    const interval = setInterval(() => load().catch(() => {}), 3_000)
    return () => clearInterval(interval)
  }, [capturing])

  const servers = useMemo(() => {
    const map = new Map<string, number>()
    for (const obs of observations) {
      const key = obs.server_ip || obs.server_mac
      if (!key) continue
      map.set(key, (map.get(key) ?? 0) + 1)
    }
    return [...map.entries()]
  }, [observations])

  const unknownServers = useMemo(() => observations.filter((obs) => !obs.is_authorized).length, [observations])

  async function addAuthorizedServer() {
    if (!allowlistName.trim() || (!allowlistIp.trim() && !allowlistMac.trim())) {
      toast.error(t('dhcp_allowlist_required'))
      return
    }
    setAllowlistSaving(true)
    try {
      await dhcpMonitorApi.createAuthorizedServer({
        name: allowlistName.trim(),
        server_ip: allowlistIp.trim() || null,
        server_mac: allowlistMac.trim() || null,
        enabled: true,
      })
      setAllowlistName('')
      setAllowlistIp('')
      setAllowlistMac('')
      toast.success(t('dhcp_allowlist_saved'))
      await load()
    } catch {
      toast.error(t('dhcp_allowlist_save_failed'))
    } finally {
      setAllowlistSaving(false)
    }
  }

  async function toggleAuthorizedServer(row: DhcpAuthorizedServer) {
    try {
      await dhcpMonitorApi.updateAuthorizedServer(row.id, { enabled: !row.enabled })
      await load()
    } catch {
      toast.error(t('dhcp_allowlist_save_failed'))
    }
  }

  async function deleteAuthorizedServer(id: number) {
    try {
      await dhcpMonitorApi.deleteAuthorizedServer(id)
      toast.success(t('dhcp_allowlist_deleted'))
      await load()
    } catch {
      toast.error(t('dhcp_allowlist_delete_failed'))
    }
  }

  async function startProbe() {
    try {
      const result = await dhcpMonitorApi.capture(20)
      if (!result.success) {
        toast.error(result.message || t('dhcp_capture_already_running'))
        await load().catch(() => {})
        return
      }
      setCapturing(true)
      toast.success(t('dhcp_probe_started'))
      setTimeout(() => load().catch(() => {}), 2_000)
    } catch {
      toast.error(t('dhcp_probe_failed'))
    }
  }

  async function startRequestSniffing() {
    try {
      const result = await dhcpMonitorApi.sniffRequests(30)
      if (!result.success) {
        toast.error(result.message || t('dhcp_capture_already_running'))
        await load().catch(() => {})
        return
      }
      setCapturing(true)
      toast.success(t('dhcp_sniff_started'))
      setTimeout(() => load().catch(() => {}), 2_000)
    } catch {
      toast.error(t('dhcp_sniff_failed'))
    }
  }

  if (!uiSettingsChecked || uiSettingsLoading || loading) return <div className="flex justify-center py-16"><Spinner size="lg" /></div>

  if (!advancedViewEnabled) {
    return (
      <Card>
        <h1 className="text-xl font-bold text-text-base mb-2">{t('nav_dhcp_monitor')}</h1>
        <p className="text-sm text-text-subtle">{t('advanced_view_required')}</p>
      </Card>
    )
  }

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
          <Button variant="outline" onClick={startRequestSniffing} disabled={capturing}>{capturing ? t('dhcp_capture_running') : t('dhcp_sniff_30s')}</Button>
          <Button onClick={startProbe} disabled={capturing}>{capturing ? t('dhcp_capture_running') : t('dhcp_probe_20s')}</Button>
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
            <p className="text-xs text-text-subtle uppercase tracking-wide">{t('dhcp_unknown_servers')}</p>
            <p className={unknownServers > 0 ? 'text-2xl font-semibold text-danger' : 'text-2xl font-semibold text-success'}>{unknownServers}</p>
          </div>
        </div>
      </Card>

      <Card>
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h2 className="text-lg font-semibold text-text-base">{t('dhcp_allowlist_title')}</h2>
            <p className="text-sm text-text-subtle">{t('dhcp_allowlist_hint')}</p>
          </div>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-[1.2fr_1fr_1fr_auto]">
          <Input placeholder={t('name')} value={allowlistName} onChange={(e) => setAllowlistName(e.target.value)} />
          <Input placeholder={t('dhcp_server_ip')} value={allowlistIp} onChange={(e) => setAllowlistIp(e.target.value)} />
          <Input placeholder={t('dhcp_server_mac')} value={allowlistMac} onChange={(e) => setAllowlistMac(e.target.value)} />
          <Button onClick={addAuthorizedServer} loading={allowlistSaving}>{t('add')}</Button>
        </div>
        <div className="mt-4 overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead className="bg-surface2 text-text-subtle text-xs uppercase tracking-wide">
              <tr>
                <th className="text-left px-3 py-2">{t('name')}</th>
                <th className="text-left px-3 py-2">{t('dhcp_server_ip')}</th>
                <th className="text-left px-3 py-2">{t('dhcp_server_mac')}</th>
                <th className="text-left px-3 py-2">{t('col_status')}</th>
                <th className="text-right px-3 py-2">{t('actions')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {authorizedServers.length === 0 ? (
                <tr><td className="px-3 py-3 text-text-subtle" colSpan={5}>{t('dhcp_allowlist_empty')}</td></tr>
              ) : authorizedServers.map((row) => (
                <tr key={row.id}>
                  <td className="px-3 py-2 font-medium text-text-base">{row.name}</td>
                  <td className="px-3 py-2 font-mono text-text-muted">{row.server_ip || '—'}</td>
                  <td className="px-3 py-2 font-mono text-text-muted">{row.server_mac || '—'}</td>
                  <td className="px-3 py-2"><Badge variant={row.enabled ? 'success' : 'muted'}>{row.enabled ? t('enabled') : t('disabled')}</Badge></td>
                  <td className="px-3 py-2">
                    <div className="flex justify-end gap-2">
                      <Button size="sm" variant="outline" onClick={() => toggleAuthorizedServer(row)}>{row.enabled ? t('disable') : t('enable')}</Button>
                      <Button size="sm" variant="ghost" onClick={() => deleteAuthorizedServer(row.id)}>{t('delete')}</Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card>
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <p className="text-xs text-text-subtle uppercase tracking-wide">{t('dhcp_allowlisted_servers')}</p>
            <p className="text-2xl font-semibold text-text-base">{authorizedServers.filter((row) => row.enabled).length}</p>
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
                        <div className="mt-1">
                          <Badge variant={obs.is_authorized ? 'success' : 'danger'}>
                            {obs.is_authorized ? (obs.authorized_server_name || t('dhcp_authorized')) : t('dhcp_unauthorized')}
                          </Badge>
                        </div>
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
