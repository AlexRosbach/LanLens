import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import toast from 'react-hot-toast'
import { credentialsApi, type Credential } from '../../api/credentials'
import {
  deepScanApi,
  type AgentStatus,
  type DeepScanConfig,
  type DeepScanFinding,
  type DeepScanRun,
  type DeviceHostRelationship,
} from '../../api/deepScan'
import { useI18n } from '../../i18n'
import { formatRelativeTime } from '../../utils/formatters'
import { hardwareFallbackFindings, preferredVmwareHardware } from '../../utils/hardwareInventory'
import Button from '../ui/Button'
import Badge from '../ui/Badge'
import DeepScanConfigForm from './DeepScanConfigForm'
import FindingsGrid from './FindingsGrid'
import HostGuestPanel from './HostGuestPanel'
import VsphereDeviceInventory from './VsphereDeviceInventory'
import type { VsphereDeviceObservation } from '../../api/devices'

const SOURCE_LABELS: Record<string, string> = { windows_agent: 'Windows Agent', linux_agent: 'Linux Agent', winrm: 'WinRM', ssh: 'SSH', vsphere: 'VMware / vSphere', unknown: 'Unknown' }
const sourceOf = (f: DeepScanFinding) => f.collection_source || (f.source === 'lanlens_windows_agent' ? 'windows_agent' : f.source === 'lanlens_linux_agent' ? 'linux_agent' : f.source === 'winrm/ps' ? 'winrm' : 'unknown')

type Tab = 'hardware' | 'os' | 'applications' | 'service' | 'container' | 'audit' | 'hypervisor' | 'host_guest' | 'vsphere'

const TABS: { key: Tab; labelKey: string }[] = [
  { key: 'hardware',    labelKey: 'tab_hardware' },
  { key: 'os',         labelKey: 'tab_os' },
  { key: 'applications', labelKey: 'tab_applications' },
  { key: 'service',    labelKey: 'tab_services' },
  { key: 'container',  labelKey: 'tab_containers' },
  { key: 'audit',      labelKey: 'tab_audit' },
  { key: 'hypervisor', labelKey: 'tab_hypervisor' },
  { key: 'host_guest', labelKey: 'tab_host_guest' },
  { key: 'vsphere', labelKey: 'vsphere_title' },
]

function StatusBadge({ run }: { run: DeepScanRun | null }) {
  const { t } = useI18n()
  if (!run) return null
  const map: Record<string, { variant: 'success' | 'danger' | 'warning' | 'primary' | 'muted'; labelKey: string }> = {
    done:    { variant: 'success', labelKey: 'deep_scan_status_done' },
    error:   { variant: 'danger',  labelKey: 'deep_scan_status_error' },
    running: { variant: 'primary', labelKey: 'deep_scan_status_running' },
    skipped: { variant: 'muted',   labelKey: 'deep_scan_status_skipped' },
  }
  const info = map[run.status] ?? map.skipped
  return <Badge variant={info.variant}>{t(info.labelKey as Parameters<typeof t>[0])}</Badge>
}

interface Props {
  deviceId: number
  vmware?: VsphereDeviceObservation[]
  onScanCompleted?: () => void | Promise<void>
}

export default function DeepScanPanel({ deviceId, onScanCompleted, vmware = [] }: Props) {
  const { t, lang } = useI18n()

  const [config, setConfig] = useState<DeepScanConfig | null>(null)
  const [agentStatus, setAgentStatus] = useState<AgentStatus | null>(null)
  const [sourceFilter, setSourceFilter] = useState('all')
  const [loadError, setLoadError] = useState(false)
  const [latestRun, setLatestRun] = useState<DeepScanRun | null>(null)
  const [findings, setFindings] = useState<DeepScanFinding[]>([])
  const [relationships, setRelationships] = useState<DeviceHostRelationship[]>([])
  const [credentials, setCredentials] = useState<Credential[]>([])
  const [activeTab, setActiveTab] = useState<Tab>('hardware')
  const [showConfig, setShowConfig] = useState(false)
  const [triggering, setTriggering] = useState(false)
  const [loading, setLoading] = useState(true)

  const load = async () => {
    try {
      const [cfgResp, runsResp, findingsResp, relsResp, credsResp, agentResp] = await Promise.all([
        deepScanApi.getConfig(deviceId),
        deepScanApi.listRuns(deviceId, 1),
        deepScanApi.getFindings(deviceId),
        deepScanApi.getRelationships(deviceId),
        credentialsApi.list(),
        deepScanApi.getAgentStatus(deviceId),
      ])
      setLoadError(false)
      setAgentStatus(agentResp.data)
      setConfig(cfgResp.data)
      setLatestRun(runsResp.data[0] ?? null)
      setFindings(findingsResp.data)
      setRelationships(relsResp.data)
      setCredentials(credsResp.data)
    } catch {
      setLoadError(true)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    setSourceFilter('all')
    setAgentStatus(null)
    setFindings([])
    load()
  }, [deviceId])

  // Outbound reports can arrive without a credential scan running.
  useEffect(() => {
    let active = true
    const refresh = async () => {
      try {
        const [runs, data, agent] = await Promise.all([deepScanApi.listRuns(deviceId, 1), deepScanApi.getFindings(deviceId), deepScanApi.getAgentStatus(deviceId)])
        if (!active) return
        setLatestRun(runs.data[0] ?? null)
        setFindings(data.data)
        setAgentStatus(agent.data)
        setLoadError(false)
      } catch { if (active) setLoadError(true) }
    }
    const timer = window.setInterval(refresh, 15000)
    window.addEventListener('focus', refresh)
    return () => { active = false; window.clearInterval(timer); window.removeEventListener('focus', refresh) }
  }, [deviceId])

  // Poll if a scan is running
  useEffect(() => {
    if (latestRun?.status !== 'running') return

    let lastSeenRunId = latestRun.id
    let lastSeenStatus: DeepScanRun['status'] = latestRun.status

    const timer = setInterval(() => {
      deepScanApi.listRuns(deviceId, 1).then((r) => {
        const run = r.data[0] ?? null
        setLatestRun(run)

        if (!run) return

        const statusChanged = run.id === lastSeenRunId && run.status !== lastSeenStatus
        lastSeenRunId = run.id
        lastSeenStatus = run.status

        if (run.status === 'done') {
          deepScanApi.getFindings(deviceId).then((fr) => setFindings(fr.data))
          deepScanApi.getRelationships(deviceId).then((rr) => setRelationships(rr.data))
          if (statusChanged) {
            Promise.resolve(onScanCompleted?.()).catch(() => {})
          }
        }

        if (statusChanged && run.status === 'error') {
          toast.error(run.error_message || t('deep_scan_status_error'))
        }
      }).catch(() => {
        // ignore transient polling failures
      })
    }, 3000)
    return () => clearInterval(timer)
  }, [deviceId, latestRun?.id, latestRun?.status, onScanCompleted, t])

  const handleTrigger = async () => {
    setTriggering(true)
    try {
      await deepScanApi.triggerScan(deviceId)
      toast.success(t('deep_scan_running'))
      // Refresh runs immediately to show the running state
      const runsResp = await deepScanApi.listRuns(deviceId, 1)
      setLatestRun(runsResp.data[0] ?? null)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(msg || t('failed_to_start_deep_scan'))
    } finally {
      setTriggering(false)
    }
  }

  const preferredHardware = preferredVmwareHardware(vmware)
  const hardwareObservations = sourceFilter === 'vsphere'
    ? vmware.map(row => ({ ...row, fields: Object.fromEntries(Object.entries(row.fields).filter(([key]) => ['cpu_count', 'memory_size_mib', 'disks'].includes(key))), custom_fields: [] })).filter(row => Object.keys(row.fields).length > 0)
    : preferredHardware
  const combinedFindings = sourceFilter === 'all' ? hardwareFallbackFindings(findings, preferredHardware) : findings

  const findingsByTab = (tab: Tab) => {
    if (tab === 'host_guest') return []
    // Inventory collectors store installed applications under the stable
    // `software` finding type. Present it as a dedicated Applications tab so
    // it is easy to find next to Operating System in the device Deep Scan.
    const findingType = tab === 'applications' ? 'software' : tab
    return combinedFindings.filter((f) => f.finding_type === findingType && (sourceFilter === 'all' || sourceOf(f) === sourceFilter))
  }

  // Only show tabs that have data (or are always shown)
  const visibleTabs = TABS.filter((tab) => {
    if (tab.key === 'vsphere') return vmware.length > 0 && ['all','vsphere'].includes(sourceFilter)
    if (tab.key === 'hardware' && ['all','vsphere'].includes(sourceFilter) && hardwareObservations.length > 0) return true
    if (tab.key === 'host_guest') return Boolean(config?.enabled || relationships.length)
    return findingsByTab(tab.key).length > 0
  })

  const sourceGroups = [...new Set(findings.map(sourceOf))].sort()
  const activeSources = new Set<string>()
  const credential = credentials.find(c => c.id === config?.credential_id)
  if (config?.enabled && credential) {
    if (credential.credential_type === 'windows_winrm') activeSources.add('winrm')
    if (credential.credential_type === 'linux_ssh') activeSources.add('ssh')
  }
  if (agentStatus && !agentStatus.revoked) activeSources.add(agentStatus.platform === 'linux' ? 'linux_agent' : 'windows_agent')
  if (vmware.length) activeSources.add('vsphere')
  const sources = [...new Set([...activeSources, ...sourceGroups, ...(vmware.length ? ['vsphere'] : [])])].sort()
  const sourceCount = (source: string) => source === 'vsphere' ? vmware.length : findings.filter(f=>sourceOf(f)===source).length
  const german = lang === 'de'
  const agentRecoveryRunHint = agentStatus?.platform === 'linux'
    ? (german ? 'Führe den neuen Befehl auf diesem Gerät als root oder mit sudo aus.' : 'Run the new command on this device as root or with sudo.')
    : (german ? 'Führe den neuen Befehl auf diesem Gerät als Administrator in PowerShell aus.' : 'Run the new command on this device as administrator in PowerShell.')
  const filteredSources = sourceGroups.filter(source => sourceFilter === 'all' || sourceFilter === source)
  // Keep activeTab in sync: if the current tab is not visible, switch to the first visible one
  const effectiveTab: Tab = visibleTabs.some((t) => t.key === activeTab)
    ? activeTab
    : (visibleTabs[0]?.key ?? 'host_guest')

  useEffect(() => {
    if (!loading && effectiveTab !== activeTab) {
      setActiveTab(effectiveTab)
    }
  }, [activeTab, effectiveTab, loading])

  if (loading) {
    return (
      <div className="py-6 text-center text-sm text-text-subtle">{t('deep_scan_running')}</div>
    )
  }

  const canTrigger =
    Boolean(config?.enabled && config?.credential_id && latestRun?.status !== 'running')

  return (
    <div className="space-y-4">
      {/* Header row */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <StatusBadge run={latestRun} />
          {latestRun && (
            <span className="text-xs text-text-subtle">
              {latestRun.status === 'error' && latestRun.error_message
                ? t('deep_scan_last_scan_error', {
                    time: formatRelativeTime(latestRun.started_at, lang),
                    message: latestRun.error_message,
                  })
                : `${t('deep_scan_last_scan')} ${formatRelativeTime(latestRun.started_at, lang)}`}
            </span>
          )}
          {!latestRun && (
            <span className="text-xs text-text-subtle">{t('deep_scan_never_scanned')}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowConfig(!showConfig)}
          >
            {t('deep_scan_configure')}
          </Button>
          <Button
            size="sm"
            onClick={handleTrigger}
            loading={triggering || latestRun?.status === 'running'}
            disabled={!canTrigger}
          >
            {latestRun?.status === 'running' ? t('deep_scan_running') : t('deep_scan_run')}
          </Button>
        </div>
      </div>

      {loadError && <p className="text-xs text-danger">{german ? 'Inventar konnte nicht vollständig geladen werden.' : 'Inventory could not be loaded completely.'}</p>}
      {agentStatus && <div className="rounded-lg border border-border p-3 space-y-1 text-xs">
        <div className="font-semibold text-text-base">{SOURCE_LABELS[agentStatus.platform === 'linux' ? 'linux_agent' : 'windows_agent']} · {agentStatus.revoked ? (german ? 'Widerrufen' : 'Revoked') : (agentStatus.last_seen_at ? (german ? 'Report empfangen' : 'Report received') : (german ? 'Registriert, noch kein Report' : 'Enrolled, no report yet'))}</div>
        {agentStatus.revoked && <p role="alert" className="text-danger">{german ? 'Die Registrierung wurde widerrufen. Der Server lehnt weitere Reports ab. Erstelle unter ' : 'The registration was revoked. The server rejects further reports. Create a new installation command in '}<Link className="underline" to="/deep-scan-settings">{german ? 'Deep-Scan-Einstellungen' : 'Deep Scan settings'}</Link>{german ? ' einen neuen Installationsbefehl. ' : '. '}{agentRecoveryRunHint}{german ? ' Das bisherige Inventar bleibt erhalten.' : ' Existing inventory is retained.'}</p>}
        <div className="text-text-muted">Device ID: {agentStatus.device_id} · POST /api/agents/report</div>
        <div className="text-text-muted">{german ? 'Letzter empfangener Report' : 'Last accepted report'}: {agentStatus.last_seen_at ? formatRelativeTime(agentStatus.last_seen_at, lang) : '—'} · Sequence: {agentStatus.last_sequence}{agentStatus.last_run_id ? ' · Scan #' + agentStatus.last_run_id : ''}</div>
        {agentStatus.summary && <div className="text-text-muted">{german ? 'Anwendungen' : 'Applications'}: {agentStatus.summary.software_count ?? '—'} · Findings: {agentStatus.summary.finding_count ?? '—'}</div>}
      </div>}
      {sources.length > 0 && <div className="rounded-lg border border-border p-3 space-y-2">
        <h3 className="text-xs font-semibold text-text-base">{german ? 'Datenquellen' : 'Data sources'}</h3>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={()=>setSourceFilter('all')} aria-pressed={sourceFilter === 'all'} className={sourceFilter === 'all' ? 'ring-1 ring-primary rounded-full' : ''}><Badge variant="muted">{german ? 'Alle' : 'All'}</Badge></button>
          {sources.map(source => {
            const count = sourceCount(source)
            const active = activeSources.has(source)
            const state = count > 0 ? (active ? (german ? 'Daten vorhanden' : 'Data received') : (german ? 'Historische Daten' : 'Historical data')) : (german ? 'Aktiv, noch keine Daten' : 'Active, no data yet')
            return <button type="button" key={source} aria-pressed={sourceFilter === source} title={state} onClick={()=>setSourceFilter(sourceFilter === source ? 'all' : source)} className={sourceFilter === source ? 'ring-1 ring-primary rounded-full' : ''}>
              <Badge variant={count > 0 ? 'success' : 'muted'} dot>{SOURCE_LABELS[source] || source} · {count > 0 ? count : '0'}{!active ? (german ? ' · Historie' : ' · History') : ''}</Badge>
            </button>
          })}
        </div>
        <p className="text-xs text-text-subtle">{german ? 'Grün: Daten vorhanden. Grau: aktiv, noch keine Daten. Der Zeitstempel zeigt die letzte Beobachtung, nicht den Live-Status.' : 'Green: data available. Gray: active, no data yet. The timestamp shows the last observation, not live status.'}</p>
        {sources.map(source => {
          const newest = (source === 'vsphere' ? vmware.map(f=>f.observed_at) : findings.filter(f=>sourceOf(f)===source).map(f=>f.observed_at)).sort().slice(-1)[0]
          return <p key={source} className="text-xs text-text-subtle">{SOURCE_LABELS[source] || source}: {newest ? formatRelativeTime(newest, lang) : '—'}</p>
        })}
      </div>}

      {/* Config form */}
      {showConfig && config && (
        <DeepScanConfigForm
          deviceId={deviceId}
          config={config}
          credentials={credentials}
          onSaved={(updated) => {
            setConfig(updated)
            setShowConfig(false)
          }}
        />
      )}

      {/* Not configured empty state */}
      {!config?.enabled && !showConfig && vmware.length === 0 && findings.length === 0 && !agentStatus && (
        <p className="text-sm text-text-subtle text-center py-2">
          {t('deep_scan_not_enabled')}
        </p>
      )}

      {/* Tabs + findings */}
      {sourceFilter !== 'all' && sourceCount(sourceFilter) === 0 && <p className="text-xs text-text-muted">{german ? 'Noch keine Daten aus dieser Quelle.' : 'No data from this source yet.'}</p>}
      {(config?.enabled || vmware.length > 0 || findings.length > 0 || relationships.length > 0) && (
        <>
          <div className="flex gap-1 border-b border-border overflow-x-auto">
            {visibleTabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`px-3 py-2 text-sm font-medium whitespace-nowrap transition-colors border-b-2 -mb-px ${
                  effectiveTab === tab.key
                    ? 'border-primary text-primary'
                    : 'border-transparent text-text-muted hover:text-text-base'
                }`}
              >
                {t(tab.labelKey as Parameters<typeof t>[0])}
              </button>
            ))}
          </div>

          <div className="min-h-[100px]">
            {effectiveTab === 'vsphere' ? <VsphereDeviceInventory observations={vmware} /> : effectiveTab === 'host_guest' ? (
              <HostGuestPanel
                deviceId={deviceId}
                relationships={relationships}
                onRelationshipDeleted={load}
                onSuggestionApplied={load}
              />
            ) : (
              <>
                {effectiveTab === 'hardware' && sourceFilter === 'all' && preferredHardware.length > 0 && <p className="mb-3 text-xs text-text-muted">{german ? 'Hardwaredaten aus VMware / vSphere haben Vorrang. Andere Quellen ergänzen fehlende Angaben. Über die Quellen-Badges sind die jeweiligen Originaldaten sichtbar.' : 'VMware / vSphere hardware values take precedence. Other sources supplement missing details. Select a source badge to view its original observations.'}</p>}
                {effectiveTab === 'hardware' && hardwareObservations.length > 0 && ['all','vsphere'].includes(sourceFilter) && <VsphereDeviceInventory observations={hardwareObservations} />}
                {filteredSources.map(source => { const rows = findingsByTab(effectiveTab).filter(f=>sourceOf(f)===source); return rows.length > 0 ? <div key={effectiveTab + source} className="space-y-1 mb-3"><h4 className="text-xs font-semibold text-primary">{SOURCE_LABELS[source] || source} · {rows.length} Findings</h4><FindingsGrid findings={rows} alwaysExpanded={effectiveTab === 'applications'} /></div> : null })}
              </>
            )}
          </div>
        </>
      )}

      {/* Error message from latest run */}
      {latestRun?.status === 'error' && latestRun.error_message && (
        <div className="text-xs text-danger bg-danger-dim rounded-lg p-3">
          {latestRun.error_message}
        </div>
      )}
    </div>
  )
}
