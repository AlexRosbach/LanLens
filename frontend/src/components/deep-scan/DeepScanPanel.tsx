import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { credentialsApi, type Credential } from '../../api/credentials'
import {
  deepScanApi,
  type DeepScanConfig,
  type DeepScanFinding,
  type DeepScanRun,
  type DeviceHostRelationship,
} from '../../api/deepScan'
import { useI18n } from '../../i18n'
import { formatRelativeTime } from '../../utils/formatters'
import Button from '../ui/Button'
import Badge from '../ui/Badge'
import DeepScanConfigForm from './DeepScanConfigForm'
import FindingsGrid from './FindingsGrid'
import HostGuestPanel from './HostGuestPanel'

type Tab = 'hardware' | 'os' | 'service' | 'container' | 'audit' | 'hypervisor' | 'host_guest'

const TABS: { key: Tab; labelKey: string }[] = [
  { key: 'hardware',    labelKey: 'tab_hardware' },
  { key: 'os',         labelKey: 'tab_os' },
  { key: 'service',    labelKey: 'tab_services' },
  { key: 'container',  labelKey: 'tab_containers' },
  { key: 'audit',      labelKey: 'tab_audit' },
  { key: 'hypervisor', labelKey: 'tab_hypervisor' },
  { key: 'host_guest', labelKey: 'tab_host_guest' },
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
}

export default function DeepScanPanel({ deviceId }: Props) {
  const { t, lang } = useI18n()

  const [config, setConfig] = useState<DeepScanConfig | null>(null)
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
      const [cfgResp, runsResp, findingsResp, relsResp, credsResp] = await Promise.all([
        deepScanApi.getConfig(deviceId),
        deepScanApi.listRuns(deviceId, 1),
        deepScanApi.getFindings(deviceId),
        deepScanApi.getRelationships(deviceId),
        credentialsApi.list(),
      ])
      setConfig(cfgResp.data)
      setLatestRun(runsResp.data[0] ?? null)
      setFindings(findingsResp.data)
      setRelationships(relsResp.data)
      setCredentials(credsResp.data)
    } catch {
      // silently fail — device may not have been scanned yet
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [deviceId])

  // Poll if a scan is running
  useEffect(() => {
    if (latestRun?.status !== 'running') return
    const timer = setInterval(() => {
      deepScanApi.listRuns(deviceId, 1).then((r) => {
        const run = r.data[0] ?? null
        setLatestRun(run)
        if (run?.status === 'done') {
          deepScanApi.getFindings(deviceId).then((fr) => setFindings(fr.data))
          deepScanApi.getRelationships(deviceId).then((rr) => setRelationships(rr.data))
        }
      })
    }, 3000)
    return () => clearInterval(timer)
  }, [deviceId, latestRun?.status])

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
      toast.error(msg || 'Failed to start deep scan')
    } finally {
      setTriggering(false)
    }
  }

  const findingsByTab = (tab: Tab) =>
    tab === 'host_guest' ? [] : findings.filter((f) => f.finding_type === tab)

  // Only show tabs that have data (or are always shown)
  const visibleTabs = TABS.filter((tab) => {
    if (tab.key === 'host_guest') return true
    if (tab.key === 'hypervisor') return findings.some((f) => f.finding_type === 'hypervisor')
    return findings.some((f) => f.finding_type === tab.key)
  })

  if (loading) {
    return (
      <div className="py-6 text-center text-sm text-text-subtle">{t('deep_scan_running')}</div>
    )
  }

  const canTrigger =
    config?.enabled && config?.credential_id && latestRun?.status !== 'running'

  return (
    <div className="space-y-4">
      {/* Header row */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <StatusBadge run={latestRun} />
          {latestRun && (
            <span className="text-xs text-text-subtle">
              {t('deep_scan_last_scan')}{' '}
              {formatRelativeTime(latestRun.started_at, lang)}
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
      {!config?.enabled && !showConfig && (
        <p className="text-sm text-text-subtle text-center py-2">
          {t('deep_scan_not_enabled')}
        </p>
      )}

      {/* Tabs + findings */}
      {config?.enabled && (
        <>
          <div className="flex gap-1 border-b border-border overflow-x-auto">
            {visibleTabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`px-3 py-2 text-sm font-medium whitespace-nowrap transition-colors border-b-2 -mb-px ${
                  activeTab === tab.key
                    ? 'border-primary text-primary'
                    : 'border-transparent text-text-muted hover:text-text-base'
                }`}
              >
                {t(tab.labelKey as Parameters<typeof t>[0])}
              </button>
            ))}
          </div>

          <div className="min-h-[100px]">
            {activeTab === 'host_guest' ? (
              <HostGuestPanel
                deviceId={deviceId}
                relationships={relationships}
                onRelationshipDeleted={load}
                onSuggestionApplied={load}
              />
            ) : (
              <FindingsGrid findings={findingsByTab(activeTab)} />
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
