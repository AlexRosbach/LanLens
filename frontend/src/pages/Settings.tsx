import { useEffect, useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import { Link } from 'react-router-dom'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import Input from '../components/ui/Input'
import Spinner from '../components/ui/Spinner'
import { settingsApi, type AllSettings } from '../api/settings'
import { idoitApi, type IdoitConfig, type IdoitExportRow, type IdoitSyncLogEntry } from '../api/idoit'
import { scanNodesApi, type ScanNode, type ScanNodeProvisioning } from '../api/scanNodes'
import { snmpApi, type SnmpEndpoint, type SnmpProfile, type SnmpProfileCreate, type SnmpSwitch } from '../api/snmp'
import { passiveDiscoveryApi, type PassiveDiscoveryCaptureReport } from '../api/plugins'
import { devicesApi } from '../api/devices'
import { adminApi } from '../api/admin'
import { DeviceMergeCard, DocumentationExportCard, IgnoreRulesCard, SelectiveBackupCard } from './InventoryTools'
import { useI18n } from '../i18n'
import { useUiSettingsStore } from '../store/uiSettingsStore'
import { formatDateTime } from '../utils/formatters'

interface IdoitErrorDetails {
  message: string
  stage?: string
  endpoint?: string
  status_code?: number | null
  response_body?: string
  jsonrpc_error?: unknown
}

interface IdoitMapping {
  name?: string
  version?: number
  objectType?: string
  objectTypeByDeviceClass?: Record<string, string>
  identity?: Record<string, unknown>
  fields?: Record<string, string>
}

const IDOIT_MAPPING_FIELDS = [
  { key: 'hostname', labelKey: 'idoit_field_hostname', placeholder: 'C__CATG__IP.hostname' },
  { key: 'ip_address', labelKey: 'idoit_field_ip_address', placeholder: 'C__CATG__IP.ipv4_address' },
  { key: 'mac_address', labelKey: 'idoit_field_mac_address', placeholder: 'C__CATG__NETWORK_PORT.mac' },
  { key: 'vendor', labelKey: 'idoit_field_vendor', placeholder: 'C__CATG__MODEL.manufacturer' },
  { key: 'asset_tag', labelKey: 'idoit_field_asset_tag', placeholder: 'C__CATG__ACCOUNTING.inventory_no' },
  { key: 'cmdb_id', labelKey: 'idoit_field_cmdb_id', placeholder: 'C__CATG__ACCOUNTING.inventory_no' },
  { key: 'purpose', labelKey: 'idoit_field_purpose', placeholder: '' },
  { key: 'notes', labelKey: 'idoit_field_notes', placeholder: '' },
  { key: 'os_info', labelKey: 'idoit_field_os_info', placeholder: 'C__CATG__OPERATING_SYSTEM.assigned_version' },
  { key: 'cpu', labelKey: 'idoit_field_cpu', placeholder: 'C__CATG__CPU.title' },
  { key: 'model', labelKey: 'idoit_field_model', placeholder: 'C__CATG__MODEL.title' },
  { key: 'serial', labelKey: 'idoit_field_serial', placeholder: 'C__CATG__MODEL.serial' },
  { key: 'memory', labelKey: 'idoit_field_memory', placeholder: 'C__CATG__MEMORY.title' },
  { key: 'disks', labelKey: 'idoit_field_disks', placeholder: 'C__CATG__DRIVE.title' },
  { key: 'open_ports', labelKey: 'idoit_field_open_ports', placeholder: '' },
  { key: 'services', labelKey: 'idoit_field_services', placeholder: '' },
  { key: 'tls_certificates', labelKey: 'idoit_field_tls_certificates', placeholder: '' },
  { key: 'containers', labelKey: 'idoit_field_containers', placeholder: '' },
  { key: 'hypervisor', labelKey: 'idoit_field_hypervisor', placeholder: '' },
  { key: 'licenses', labelKey: 'idoit_field_licenses', placeholder: '' },
  { key: 'relationships', labelKey: 'idoit_field_relationships', placeholder: '' },
  { key: 'lanlens_inventory', labelKey: 'idoit_field_lanlens_inventory', placeholder: '' },
  { key: 'hardware_summary', labelKey: 'idoit_field_hardware_summary', placeholder: '' },
] as const

const IDOIT_EXPORT_EDIT_FIELDS = [
  { key: 'object_type', labelKey: 'idoit_export_object_type' },
  { key: 'title', labelKey: 'idoit_export_title' },
  { key: 'ip_address', labelKey: 'idoit_field_ip_address' },
  { key: 'mac_address', labelKey: 'idoit_field_mac_address' },
  { key: 'hostname', labelKey: 'idoit_field_hostname' },
  { key: 'manufacturer', labelKey: 'idoit_export_manufacturer' },
  { key: 'model', labelKey: 'idoit_field_model' },
  { key: 'serial', labelKey: 'idoit_field_serial' },
  { key: 'os_info', labelKey: 'idoit_field_os_info' },
  { key: 'inventory_no', labelKey: 'idoit_export_inventory_no' },
  { key: 'cmdb_id', labelKey: 'idoit_field_cmdb_id' },
  { key: 'location', labelKey: 'idoit_export_location' },
  { key: 'responsible', labelKey: 'idoit_export_responsible' },
  { key: 'notes', labelKey: 'idoit_field_notes', wide: true },
  { key: 'snmp_switch', labelKey: 'idoit_export_snmp_switch' },
  { key: 'snmp_port', labelKey: 'idoit_export_snmp_port' },
  { key: 'tls_certificates', labelKey: 'idoit_field_tls_certificates', wide: true },
  { key: 'identity_confidence', labelKey: 'idoit_export_identity_confidence' },
] as const

function parseIdoitMapping(raw: string): { mapping: IdoitMapping | null; error: string | null } {
  try {
    const parsed = JSON.parse(raw || '{}')
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? { mapping: parsed as IdoitMapping, error: null }
      : { mapping: null, error: 'Mapping must be a JSON object' }
  } catch (error) {
    return { mapping: null, error: error instanceof Error ? error.message : 'Invalid JSON' }
  }
}

function stringifyIdoitMapping(mapping: IdoitMapping): string {
  return JSON.stringify(mapping, null, 2)
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  // Revoke after a tick so the browser has time to start the download
  setTimeout(() => { URL.revokeObjectURL(url); document.body.removeChild(a) }, 100)
}

function buildHttpsSettingsUrl(port: number) {
  const url = new URL(window.location.href)
  url.protocol = 'https:'
  url.port = port === 443 ? '' : String(port)
  return url.toString()
}

function extractIdoitErrorDetails(error: unknown): IdoitErrorDetails {
  const response = (error as { response?: { data?: { detail?: unknown } } })?.response
  const detail = response?.data?.detail
  if (detail && typeof detail === 'object') {
    const data = detail as Record<string, unknown>
    return {
      message: String(data.message || 'i-doit connection failed'),
      stage: typeof data.stage === 'string' ? data.stage : undefined,
      endpoint: typeof data.endpoint === 'string' ? data.endpoint : undefined,
      status_code: typeof data.status_code === 'number' ? data.status_code : null,
      response_body: typeof data.response_body === 'string' ? data.response_body : undefined,
      jsonrpc_error: data.jsonrpc_error,
    }
  }
  if (typeof detail === 'string') return { message: detail }
  return { message: (error as Error)?.message || 'i-doit connection failed' }
}

function extractApiErrorMessage(error: unknown, fallback: string): string {
  const response = (error as { response?: { data?: { detail?: unknown } } })?.response
  const detail = response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (detail && typeof detail === 'object') {
    const data = detail as Record<string, unknown>
    if (typeof data.message === 'string' && data.message.trim()) return data.message
  }
  return (error as Error)?.message || fallback
}

function ToggleSwitch({
  checked,
  disabled = false,
  onChange,
  label,
  description,
}: {
  checked: boolean
  disabled?: boolean
  onChange: (checked: boolean) => void
  label: string
  description: string
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`flex w-full items-center justify-between gap-4 rounded-lg border px-4 py-3 text-left transition-colors ${
        checked ? 'border-primary/40 bg-primary-dim/20' : 'border-border bg-surface2/40'
      } ${disabled ? 'cursor-not-allowed opacity-50' : 'hover:border-primary/50'}`}
    >
      <span>
        <span className="block text-sm font-medium text-text-base">{label}</span>
        <span className="mt-1 block text-xs text-text-subtle">{description}</span>
      </span>
      <span className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${checked ? 'bg-primary' : 'bg-border'}`}>
        <span className={`absolute top-1 h-4 w-4 rounded-full bg-white transition-transform ${checked ? 'translate-x-6' : 'translate-x-1'}`} />
      </span>
    </button>
  )
}

function IdoitExportReviewPanel() {
  const { t } = useI18n()
  const [rows, setRows] = useState<IdoitExportRow[]>([])
  const [loading, setLoading] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [registeredOnly, setRegisteredOnly] = useState(true)
  const [includeOffline, setIncludeOffline] = useState(true)

  const includedCount = rows.filter((row) => row.include).length

  async function loadPreview() {
    setLoading(true)
    try {
      const preview = await idoitApi.previewExport({
        registered_only: registeredOnly,
        include_offline: includeOffline,
        limit: 500,
      })
      setRows(preview.rows)
      toast.success(t('idoit_export_preview_loaded', { count: preview.rows.length }))
    } catch {
      toast.error(t('idoit_export_preview_failed'))
    } finally {
      setLoading(false)
    }
  }

  function updateRow(index: number, patch: Partial<IdoitExportRow>) {
    setRows((currentRows) => currentRows.map((row, rowIndex) => (
      rowIndex === index ? { ...row, ...patch } : row
    )))
  }

  function setAllIncluded(include: boolean) {
    setRows((currentRows) => currentRows.map((row) => ({ ...row, include })))
  }

  async function downloadExport() {
    if (!rows.length || includedCount === 0) {
      toast.error(t('idoit_export_no_rows'))
      return
    }
    setExporting(true)
    try {
      const blob = await idoitApi.exportCsv(rows)
      downloadBlob(blob, `lanlens-idoit-export-${new Date().toISOString().slice(0, 10)}.csv`)
      toast.success(t('idoit_export_downloaded', { count: includedCount }))
    } catch {
      toast.error(t('idoit_export_failed'))
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="mt-4 rounded-xl border border-border bg-surface2/30 p-4">
      <div className="flex flex-col gap-1 mb-4">
        <h3 className="text-sm font-semibold text-text-muted">{t('idoit_export_review')}</h3>
        <p className="text-xs text-text-subtle">{t('idoit_export_review_hint')}</p>
      </div>

      <div className="flex flex-wrap items-center gap-3 text-sm text-text-muted">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={registeredOnly} onChange={(event) => setRegisteredOnly(event.target.checked)} />
          {t('idoit_export_registered_only')}
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={includeOffline} onChange={(event) => setIncludeOffline(event.target.checked)} />
          {t('idoit_export_include_offline')}
        </label>
        <Button onClick={loadPreview} loading={loading} variant="outline">{t('idoit_export_load_preview')}</Button>
        <Button onClick={downloadExport} loading={exporting} disabled={!rows.length || includedCount === 0}>
          {t('idoit_export_download')}
        </Button>
        {rows.length > 0 && (
          <span className="text-xs text-text-subtle">
            {t('idoit_export_selected_count', { selected: includedCount, total: rows.length })}
          </span>
        )}
      </div>

      {rows.length > 0 && (
        <div className="mt-4">
          <div className="mb-2 flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => setAllIncluded(true)}>{t('select_all')}</Button>
            <Button size="sm" variant="outline" onClick={() => setAllIncluded(false)}>{t('select_none')}</Button>
          </div>
          <div className="max-h-[32rem] overflow-auto rounded-lg border border-border bg-background">
            <table className="min-w-[1400px] text-left text-xs">
              <thead className="sticky top-0 bg-surface text-text-subtle">
                <tr>
                  <th className="px-3 py-2 font-medium">{t('include')}</th>
                  {IDOIT_EXPORT_EDIT_FIELDS.map((field) => (
                    <th key={field.key} className={`px-3 py-2 font-medium ${'wide' in field && field.wide ? 'min-w-72' : 'min-w-40'}`}>
                      {t(field.labelKey)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {rows.map((row, rowIndex) => (
                  <tr key={`${row.device_id ?? rowIndex}-${rowIndex}`} className={!row.include ? 'opacity-50' : undefined}>
                    <td className="px-3 py-2 align-top">
                      <input
                        type="checkbox"
                        checked={row.include}
                        onChange={(event) => updateRow(rowIndex, { include: event.target.checked })}
                      />
                    </td>
                    {IDOIT_EXPORT_EDIT_FIELDS.map((field) => (
                      <td key={field.key} className="px-2 py-2 align-top">
                        {'wide' in field && field.wide ? (
                          <textarea
                            className="h-20 w-full rounded-lg border border-border bg-surface px-2 py-1 text-xs text-text-base focus:outline-none focus:ring-2 focus:ring-primary/40"
                            value={String(row[field.key] ?? '')}
                            onChange={(event) => updateRow(rowIndex, { [field.key]: event.target.value } as Partial<IdoitExportRow>)}
                          />
                        ) : (
                          <Input
                            className="text-xs"
                            value={String(row[field.key] ?? '')}
                            onChange={(event) => updateRow(rowIndex, { [field.key]: event.target.value } as Partial<IdoitExportRow>)}
                          />
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

export default function Settings() {
  const { t, lang, setLang } = useI18n()
  const [settings, setSettings] = useState<AllSettings | null>(null)
  const [saving, setSaving] = useState(false)
  const [checkingUpdate, setCheckingUpdate] = useState(false)
  const [httpsCertificate, setHttpsCertificate] = useState<File | null>(null)
  const [httpsPrivateKey, setHttpsPrivateKey] = useState<File | null>(null)
  const [httpsCaChain, setHttpsCaChain] = useState<File | null>(null)
  const [telegramTokenDirty, setTelegramTokenDirty] = useState(false)
  const [idoitConfig, setIdoitConfig] = useState<IdoitConfig | null>(null)
  const [idoitLoadError, setIdoitLoadError] = useState(false)
  const [idoitApiKey, setIdoitApiKey] = useState('')
  const [idoitBasicPassword, setIdoitBasicPassword] = useState('')
  const [idoitTesting, setIdoitTesting] = useState(false)
  const [idoitSyncingAll, setIdoitSyncingAll] = useState(false)
  const [idoitEnablingAll, setIdoitEnablingAll] = useState(false)
  const [idoitSyncProgress, setIdoitSyncProgress] = useState<{ current: number; total: number; success: number; failure: number; skipped: number; label?: string } | null>(null)
  const [idoitTestError, setIdoitTestError] = useState<IdoitErrorDetails | null>(null)
  const [idoitLogs, setIdoitLogs] = useState<IdoitSyncLogEntry[]>([])
  const [idoitLogsLoading, setIdoitLogsLoading] = useState(false)
  const [scanNodes, setScanNodes] = useState<ScanNode[]>([])
  const [scanNodesLoading, setScanNodesLoading] = useState(false)
  const [scanNodeName, setScanNodeName] = useState('')
  const [scanNodeSite, setScanNodeSite] = useState('')
  const [scanNodeSegment, setScanNodeSegment] = useState('')
  const [scanNodeProvisioning, setScanNodeProvisioning] = useState<ScanNodeProvisioning | null>(null)
  const [snmpProfiles, setSnmpProfiles] = useState<SnmpProfile[]>([])
  const [snmpSwitches, setSnmpSwitches] = useState<SnmpSwitch[]>([])
  const [snmpEndpoints, setSnmpEndpoints] = useState<SnmpEndpoint[]>([])
  const [snmpLoading, setSnmpLoading] = useState(false)
  const [snmpProfileName, setSnmpProfileName] = useState('')
  const [snmpVersion, setSnmpVersion] = useState<SnmpProfileCreate['version']>('2c')
  const [snmpCommunity, setSnmpCommunity] = useState('')
  const [snmpUsername, setSnmpUsername] = useState('')
  const [snmpSecurityLevel, setSnmpSecurityLevel] = useState<SnmpProfileCreate['security_level']>('authPriv')
  const [snmpAuthProtocol, setSnmpAuthProtocol] = useState<SnmpProfileCreate['auth_protocol']>('SHA')
  const [snmpAuthPassword, setSnmpAuthPassword] = useState('')
  const [snmpPrivacyProtocol, setSnmpPrivacyProtocol] = useState<SnmpProfileCreate['privacy_protocol']>('AES')
  const [snmpPrivacyPassword, setSnmpPrivacyPassword] = useState('')
  const [snmpSwitchName, setSnmpSwitchName] = useState('')
  const [snmpSwitchHost, setSnmpSwitchHost] = useState('')
  const [snmpProfileId, setSnmpProfileId] = useState('')
  const [passiveCaptureLoading, setPassiveCaptureLoading] = useState(false)
  const [passiveDiagnosticLoading, setPassiveDiagnosticLoading] = useState(false)
  const [passiveCaptureReport, setPassiveCaptureReport] = useState<PassiveDiscoveryCaptureReport | null>(null)
  const [activeSection, setActiveSection] = useState<'system' | 'features' | 'database' | 'network' | 'notifications' | 'inventory' | 'backup' | 'cmdb'>('system')
  const setAdvancedViewEnabled = useUiSettingsStore((state) => state.setAdvancedViewEnabled)
  const setShowCmdbIntegrations = useUiSettingsStore((state) => state.setShowCmdbIntegrations)
  const setShowServicesNav = useUiSettingsStore((state) => state.setShowServicesNav)
  const setShowDhcpMonitorNav = useUiSettingsStore((state) => state.setShowDhcpMonitorNav)
  const setShowPluginApi = useUiSettingsStore((state) => state.setShowPluginApi)
  const setShowPassiveDiscovery = useUiSettingsStore((state) => state.setShowPassiveDiscovery)
  const setShowMdnsDiscovery = useUiSettingsStore((state) => state.setShowMdnsDiscovery)
  const setShowSsdpDiscovery = useUiSettingsStore((state) => state.setShowSsdpDiscovery)
  const setShowTlsChecks = useUiSettingsStore((state) => state.setShowTlsChecks)
  const setShowPingHistory = useUiSettingsStore((state) => state.setShowPingHistory)
  const setShowBuildInfo = useUiSettingsStore((state) => state.setShowBuildInfo)
  const idoitMappingState = useMemo(
    () => parseIdoitMapping(idoitConfig?.idoit_mapping_raw || '{}'),
    [idoitConfig?.idoit_mapping_raw]
  )

  useEffect(() => {
    // Load settings once on mount. Language switches should only re-render labels,
    // not re-fetch and overwrite form fields or the mapping editor mid-edit.
    settingsApi.get().then((data) => {
      setSettings(data)
      setAdvancedViewEnabled(data.advanced_view_enabled)
      setShowCmdbIntegrations(data.advanced_view_enabled && data.show_cmdb_integrations)
      setShowServicesNav(data.advanced_view_enabled && data.show_services_nav)
      setShowDhcpMonitorNav(data.advanced_view_enabled && data.show_dhcp_monitor_nav)
      setShowPluginApi(data.advanced_view_enabled && data.show_plugin_api)
      setShowPassiveDiscovery(data.advanced_view_enabled && data.show_passive_discovery)
      setShowMdnsDiscovery(data.advanced_view_enabled && data.show_mdns_discovery)
      setShowSsdpDiscovery(data.advanced_view_enabled && data.show_ssdp_discovery)
      setShowTlsChecks(data.advanced_view_enabled && data.show_tls_checks)
      setShowPingHistory(data.advanced_view_enabled && data.show_ping_history)
      setShowBuildInfo(data.show_build_info)
      setTelegramTokenDirty(false)
    }).catch(() => {
      toast.error(t('settings_load_failed'))
    })
  }, [])

  useEffect(() => {
    if (settings?.advanced_view_enabled) {
      if (settings.show_cmdb_integrations) loadIdoitConfig()
      loadScanNodes().catch(() => {})
      loadSnmp().catch(() => {})
    }
  }, [settings?.advanced_view_enabled, settings?.show_cmdb_integrations])

  useEffect(() => {
    if (settings && (!settings.advanced_view_enabled || !settings.show_cmdb_integrations) && activeSection === 'cmdb') {
      setActiveSection('system')
    }
  }, [activeSection, settings])

  if (!settings) {
    return (
      <div className="flex justify-center py-16">
        <Spinner size="lg" />
      </div>
    )
  }

  const current = settings

  async function loadIdoitConfig() {
    // This endpoint is optional for the rest of Settings. If it fails, keep the
    // CMDB card usable by showing an inline retry instead of an endless spinner.
    setIdoitLoadError(false)
    try {
      const data = await idoitApi.getConfig()
      setIdoitConfig(data)
      setIdoitApiKey('')
      setIdoitBasicPassword('')
      loadIdoitLogs().catch(() => {})
    } catch {
      setIdoitConfig(null)
      setIdoitLoadError(true)
      toast.error(t('idoit_settings_load_failed'))
    }
  }

  async function loadIdoitLogs() {
    setIdoitLogsLoading(true)
    try {
      setIdoitLogs(await idoitApi.getLogs(50))
    } catch {
      toast.error(t('idoit_logs_load_failed'))
    } finally {
      setIdoitLogsLoading(false)
    }
  }

  async function loadScanNodes() {
    setScanNodesLoading(true)
    try {
      setScanNodes(await scanNodesApi.list())
    } catch {
      toast.error('Scan Nodes konnten nicht geladen werden')
    } finally {
      setScanNodesLoading(false)
    }
  }

  async function loadSnmp() {
    setSnmpLoading(true)
    try {
      const [profiles, switches, endpoints] = await Promise.all([
        snmpApi.listProfiles(),
        snmpApi.listSwitches(),
        snmpApi.listEndpoints(),
      ])
      setSnmpProfiles(profiles)
      setSnmpSwitches(switches)
      setSnmpEndpoints(endpoints)
      if (!snmpProfileId && profiles[0]) setSnmpProfileId(String(profiles[0].id))
    } catch {
      toast.error(t('snmp_load_failed'))
    } finally {
      setSnmpLoading(false)
    }
  }

  async function startPassiveDiscoveryCapture() {
    setPassiveCaptureLoading(true)
    try {
      await passiveDiscoveryApi.capture(30)
      toast.success('Passive discovery capture started')
    } catch {
      toast.error('Passive discovery capture failed')
    } finally {
      setPassiveCaptureLoading(false)
    }
  }

  async function runPassiveDiscoveryDiagnostics() {
    setPassiveDiagnosticLoading(true)
    try {
      const report = await passiveDiscoveryApi.diagnostics(10)
      setPassiveCaptureReport(report)
      if (report.errors.length > 0) {
        toast.error(report.errors[0])
      } else if (report.packets_seen === 0) {
        toast.error(t('multicast_discovery_no_packets'))
      } else {
        toast.success(t('multicast_discovery_diagnostic_result', {
          packets: report.packets_seen,
          stored: report.observations_stored,
        }))
      }
    } catch {
      toast.error(t('multicast_discovery_diagnostics_failed'))
    } finally {
      setPassiveDiagnosticLoading(false)
    }
  }

  async function createSnmpProfile() {
    const needsCommunity = snmpVersion !== '3'
    const needsAuth = snmpVersion === '3' && ['authNoPriv', 'authPriv'].includes(snmpSecurityLevel)
    const needsPrivacy = snmpVersion === '3' && snmpSecurityLevel === 'authPriv'
    if (
      !snmpProfileName.trim()
      || (needsCommunity && !snmpCommunity.trim())
      || (snmpVersion === '3' && !snmpUsername.trim())
      || (needsAuth && !snmpAuthPassword.trim())
      || (needsPrivacy && !snmpPrivacyPassword.trim())
    ) return
    setSnmpLoading(true)
    try {
      await snmpApi.createProfile({
        name: snmpProfileName.trim(),
        version: snmpVersion,
        community: snmpCommunity.trim(),
        username: snmpUsername.trim(),
        security_level: snmpSecurityLevel,
        auth_protocol: snmpAuthProtocol,
        auth_password: snmpAuthPassword.trim(),
        privacy_protocol: snmpPrivacyProtocol,
        privacy_password: snmpPrivacyPassword.trim(),
        port: 161,
        enabled: true,
      })
      setSnmpProfileName('')
      setSnmpCommunity('')
      setSnmpUsername('')
      setSnmpAuthPassword('')
      setSnmpPrivacyPassword('')
      await loadSnmp()
      toast.success(t('snmp_profile_saved'))
    } catch {
      toast.error(t('snmp_profile_save_failed'))
    } finally {
      setSnmpLoading(false)
    }
  }

  async function createSnmpSwitch() {
    if (!snmpSwitchName.trim() || !snmpSwitchHost.trim() || !snmpProfileId) return
    setSnmpLoading(true)
    try {
      await snmpApi.createSwitch({
        name: snmpSwitchName.trim(),
        host: snmpSwitchHost.trim(),
        profile_id: Number(snmpProfileId),
        enabled: true,
      })
      setSnmpSwitchName('')
      setSnmpSwitchHost('')
      await loadSnmp()
      toast.success(t('snmp_switch_saved'))
    } catch {
      toast.error(t('snmp_switch_save_failed'))
    } finally {
      setSnmpLoading(false)
    }
  }

  async function pollSnmpSwitch(switchId: number) {
    setSnmpLoading(true)
    try {
      await snmpApi.pollSwitch(switchId)
      await loadSnmp()
      toast.success(t('snmp_poll_complete'))
    } catch (error) {
      toast.error(`${t('snmp_poll_failed')}: ${extractApiErrorMessage(error, t('snmp_poll_failed'))}`)
    } finally {
      setSnmpLoading(false)
    }
  }

  async function deleteSnmpProfile(profile: SnmpProfile) {
    if (!confirm(t('snmp_profile_delete_confirm', { name: profile.name }))) return
    setSnmpLoading(true)
    try {
      await snmpApi.deleteProfile(profile.id)
      if (snmpProfileId === String(profile.id)) setSnmpProfileId('')
      await loadSnmp()
      toast.success(t('snmp_profile_deleted'))
    } catch (error) {
      toast.error(`${t('snmp_profile_delete_failed')}: ${extractApiErrorMessage(error, t('snmp_profile_delete_failed'))}`)
    } finally {
      setSnmpLoading(false)
    }
  }

  async function deleteSnmpSwitch(item: SnmpSwitch) {
    if (!confirm(t('snmp_switch_delete_confirm', { name: item.name }))) return
    setSnmpLoading(true)
    try {
      await snmpApi.deleteSwitch(item.id)
      await loadSnmp()
      toast.success(t('snmp_switch_deleted'))
    } catch (error) {
      toast.error(`${t('snmp_switch_delete_failed')}: ${extractApiErrorMessage(error, t('snmp_switch_delete_failed'))}`)
    } finally {
      setSnmpLoading(false)
    }
  }

  async function createScanNode() {
    if (!scanNodeName.trim()) {
      toast.error('Name fehlt')
      return
    }
    setScanNodesLoading(true)
    try {
      const created = await scanNodesApi.create({ name: scanNodeName.trim(), site: scanNodeSite.trim(), segment_label: scanNodeSegment.trim() })
      setScanNodeProvisioning(created)
      setScanNodeName('')
      setScanNodeSite('')
      setScanNodeSegment('')
      await loadScanNodes()
      toast.success('Scan Node erstellt')
    } catch {
      toast.error('Scan Node konnte nicht erstellt werden')
    } finally {
      setScanNodesLoading(false)
    }
  }

  async function rotateScanNodeToken(id: number) {
    setScanNodesLoading(true)
    try {
      const rotated = await scanNodesApi.rotateToken(id)
      setScanNodeProvisioning(rotated)
      await loadScanNodes()
      toast.success('Neuer Token erzeugt')
    } catch {
      toast.error('Token konnte nicht rotiert werden')
    } finally {
      setScanNodesLoading(false)
    }
  }

  async function deleteScanNode(id: number) {
    setScanNodesLoading(true)
    try {
      await scanNodesApi.delete(id)
      await loadScanNodes()
      toast.success('Scan Node geloescht')
    } catch {
      toast.error('Scan Node konnte nicht geloescht werden')
    } finally {
      setScanNodesLoading(false)
    }
  }

  async function copyScanNodeCommand() {
    if (!scanNodeProvisioning?.install_command) return
    await navigator.clipboard.writeText(scanNodeProvisioning.install_command)
    toast.success('Einzeiler kopiert')
  }

  async function saveTelegram() {
    setSaving(true)
    try {
      await settingsApi.updateTelegram({
        telegram_bot_token: current.telegram_bot_token,
        telegram_chat_id: current.telegram_chat_id,
        telegram_enabled: current.telegram_enabled,
        notify_telegram_update: current.notify_telegram_update,
        notify_on_new_device: current.notify_on_new_device,
      })
      setSettings({ ...current, telegram_bot_token: current.telegram_bot_token ? '••••••••' : '' })
      setTelegramTokenDirty(false)
      toast.success(t('telegram_settings_saved'))
    } catch {
      toast.error(t('telegram_settings_save_failed'))
    } finally {
      setSaving(false)
    }
  }

  async function saveDhcp() {
    setSaving(true)
    try {
      await settingsApi.updateDhcp(current.dhcp_start, current.dhcp_end)
      toast.success(t('dhcp_range_saved'))
    } catch {
      toast.error(t('dhcp_range_save_failed'))
    } finally {
      setSaving(false)
    }
  }

  async function saveScanRange() {
    setSaving(true)
    try {
      await settingsApi.updateScanRange(current.scan_start, current.scan_end, current.scan_additional_targets)
      toast.success(t('scan_range_saved'))
    } catch {
      toast.error(t('scan_range_save_failed'))
    } finally {
      setSaving(false)
    }
  }

  async function saveSchedule() {
    setSaving(true)
    try {
      await settingsApi.updateScanSchedule(current.scan_interval_minutes)
      toast.success(t('scan_interval_saved'))
    } catch {
      toast.error(t('scan_interval_save_failed'))
    } finally {
      setSaving(false)
    }
  }

  async function savePassiveDiscoverySchedule() {
    setSaving(true)
    try {
      await settingsApi.updatePassiveDiscovery({
        passive_discovery_background_enabled: current.passive_discovery_background_enabled,
        passive_discovery_interval_minutes: current.passive_discovery_interval_minutes,
        passive_discovery_capture_seconds: current.passive_discovery_capture_seconds,
      })
      toast.success(t('multicast_discovery_saved'))
    } catch {
      toast.error(t('multicast_discovery_save_failed'))
    } finally {
      setSaving(false)
    }
  }

  async function savePingMonitorSchedule() {
    setSaving(true)
    try {
      await settingsApi.updatePingMonitor({
        ping_monitor_enabled: current.ping_monitor_enabled,
        ping_monitor_interval_minutes: current.ping_monitor_interval_minutes,
      })
      toast.success(t('ping_monitor_saved'))
    } catch {
      toast.error(t('ping_monitor_save_failed'))
    } finally {
      setSaving(false)
    }
  }

  async function savePortScanSettings() {
    setSaving(true)
    try {
      await settingsApi.updatePortScanSettings(current.port_scan_range)
      toast.success(t('port_scan_settings_saved'))
    } catch {
      toast.error(t('port_scan_settings_save_failed'))
    } finally {
      setSaving(false)
    }
  }

  async function saveServerUrl() {
    setSaving(true)
    try {
      await settingsApi.updateServerUrl(current.server_url)
      toast.success(t('server_url_saved'))
    } catch {
      toast.error(t('server_url_save_failed'))
    } finally {
      setSaving(false)
    }
  }

  async function saveHttpsSettings() {
    setSaving(true)
    const switchesToHttps = current.https_enabled && window.location.protocol === 'http:'
    const nextSettings = {
      ...current,
      https_enabled: current.https_enabled,
      https_port: current.https_port,
      https_redirect_http: current.https_redirect_http,
      https_configured: current.https_configured || Boolean(httpsCertificate && httpsPrivateKey),
    }
    const redirectUrl = switchesToHttps ? buildHttpsSettingsUrl(current.https_port) : null
    try {
      await settingsApi.updateHttps({
        enabled: current.https_enabled,
        https_port: current.https_port,
        redirect_http: current.https_redirect_http,
        certificate: httpsCertificate,
        private_key: httpsPrivateKey,
        ca_chain: httpsCaChain,
      })
      setSettings(nextSettings)
      setHttpsCertificate(null)
      setHttpsPrivateKey(null)
      setHttpsCaChain(null)
      toast.success(t('https_settings_saved'))
      if (redirectUrl) {
        window.setTimeout(() => {
          window.location.href = redirectUrl
        }, 1000)
      }
    } catch (error) {
      const hasServerResponse = Boolean((error as { response?: unknown })?.response)
      if (!hasServerResponse && redirectUrl) {
        setSettings(nextSettings)
        setHttpsCertificate(null)
        setHttpsPrivateKey(null)
        setHttpsCaChain(null)
        toast.success(t('https_settings_saved'))
        window.setTimeout(() => {
          window.location.href = redirectUrl
        }, 1000)
        return
      }
      toast.error(t('https_settings_save_failed'))
    } finally {
      setSaving(false)
    }
  }

  async function testTelegram() {
    try {
      await settingsApi.testTelegram()
      toast.success(t('test_message_sent'))
    } catch {
      toast.error(t('telegram_test_failed'))
    }
  }

  async function saveSmtp() {
    setSaving(true)
    try {
      await settingsApi.updateSmtp({
        smtp_host: current.smtp_host,
        smtp_port: current.smtp_port,
        smtp_username: current.smtp_username,
        smtp_password: current.smtp_password,
        smtp_from_email: current.smtp_from_email,
        smtp_to_email: current.smtp_to_email,
        smtp_enabled: current.smtp_enabled,
        smtp_use_tls: current.smtp_use_tls,
      })
      toast.success(t('email_settings_saved'))
    } catch {
      toast.error(t('email_settings_save_failed'))
    } finally {
      setSaving(false)
    }
  }

  async function testSmtp() {
    try {
      await settingsApi.testSmtp()
      toast.success(t('test_email_sent'))
    } catch {
      toast.error(t('smtp_test_failed'))
    }
  }

  async function saveWebhook() {
    setSaving(true)
    try {
      await settingsApi.updateWebhook({
        webhook_url: current.webhook_url,
        webhook_enabled: current.webhook_enabled,
      })
      toast.success(t('webhook_settings_saved'))
    } catch {
      toast.error(t('webhook_settings_save_failed'))
    } finally {
      setSaving(false)
    }
  }

  async function testWebhook() {
    try {
      await settingsApi.testWebhook()
      toast.success(t('test_webhook_sent'))
    } catch {
      toast.error(t('webhook_test_failed'))
    }
  }

  async function checkForUpdates() {
    setCheckingUpdate(true)
    try {
      const result = await settingsApi.checkUpdate()
      if (result.update_available) {
        toast.success(
          t('update_available', { version: result.latest_version })
        )
      } else {
        toast.success(
          t('no_update_available', { version: result.current_version })
        )
      }
    } catch {
      toast.error(t('update_check_failed'))
    } finally {
      setCheckingUpdate(false)
    }
  }

  async function handleExportSettings() {
    try {
      const resp = await adminApi.exportSettings()
      downloadBlob(resp.data, 'lanlens-settings.json')
    } catch {
      toast.error(t('export_failed'))
    }
  }

  async function handleExportDatabase() {
    try {
      const resp = await adminApi.exportDatabase()
      const filename = adminApi.getFilenameFromDisposition(
        resp.headers['content-disposition'],
        'lanlens-backup.db'
      )
      downloadBlob(resp.data, filename)
    } catch {
      toast.error(t('database_export_failed'))
    }
  }

  async function handleImportSettings(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const result = await adminApi.importSettings(file)
      toast.success(result.data.message || t('settings_imported'))
      settingsApi.get().then((data) => {
        setSettings(data)
        setAdvancedViewEnabled(data.advanced_view_enabled)
        setShowCmdbIntegrations(data.advanced_view_enabled && data.show_cmdb_integrations)
        setShowServicesNav(data.advanced_view_enabled && data.show_services_nav)
        setShowDhcpMonitorNav(data.advanced_view_enabled && data.show_dhcp_monitor_nav)
        setShowPluginApi(data.advanced_view_enabled && data.show_plugin_api)
        setShowPassiveDiscovery(data.advanced_view_enabled && data.show_passive_discovery)
        setShowMdnsDiscovery(data.advanced_view_enabled && data.show_mdns_discovery)
        setShowSsdpDiscovery(data.advanced_view_enabled && data.show_ssdp_discovery)
        setShowTlsChecks(data.advanced_view_enabled && data.show_tls_checks)
        setShowPingHistory(data.advanced_view_enabled && data.show_ping_history)
        setShowBuildInfo(data.show_build_info)
      })
    } catch {
      toast.error(t('import_failed'))
    }
    e.target.value = '' // reset file input
  }

  async function saveCmdb() {
    setSaving(true)
    try {
      await settingsApi.updateCmdb(current.cmdb_id_prefix, current.cmdb_id_digits)
      toast.success(t('cmdb_settings_saved'))
    } catch {
      toast.error(t('cmdb_settings_save_failed'))
    } finally {
      setSaving(false)
    }
  }

  async function saveIdoit() {
    if (!idoitConfig) return
    setSaving(true)
    try {
      const payload = {
        idoit_enabled: idoitConfig.idoit_enabled,
        idoit_base_url: idoitConfig.idoit_base_url,
        idoit_jsonrpc_path: idoitConfig.idoit_jsonrpc_path,
        idoit_portal_url: idoitConfig.idoit_portal_url,
        idoit_timeout_seconds: idoitConfig.idoit_timeout_seconds,
        idoit_basic_username: idoitConfig.idoit_basic_username,
        idoit_default_object_type: idoitConfig.idoit_default_object_type,
        idoit_auto_sync_enabled: idoitConfig.idoit_auto_sync_enabled,
        idoit_sync_scope: idoitConfig.idoit_sync_scope,
        idoit_create_policy: idoitConfig.idoit_create_policy,
        idoit_sync_interval_minutes: idoitConfig.idoit_sync_interval_minutes,
        idoit_offline_retire_days: idoitConfig.idoit_offline_retire_days,
        idoit_sync_status_field: idoitConfig.idoit_sync_status_field,
        idoit_mapping_json: idoitConfig.idoit_mapping_raw,
        // Do not send an empty API key: the backend interprets omitted as
        // "keep existing secret", while an explicit non-empty value rotates it.
        ...(idoitApiKey ? { idoit_api_key: idoitApiKey } : {}),
        ...(idoitBasicPassword ? { idoit_basic_password: idoitBasicPassword } : {}),
      }
      const updated = await idoitApi.updateConfig(payload)
      setIdoitConfig(updated)
      setIdoitApiKey('')
      setIdoitBasicPassword('')
      setIdoitTestError(null)
      toast.success(t('idoit_settings_saved'))
    } catch (error) {
      const details = extractIdoitErrorDetails(error)
      setIdoitTestError({ ...details, message: details.message || t('idoit_settings_save_failed') })
      toast.error(details.message || t('idoit_settings_save_failed'))
    } finally {
      setSaving(false)
    }
  }

  async function testIdoitConnection() {
    if (!idoitConfig) return
    setIdoitTesting(true)
    try {
      const result = await idoitApi.testConnection({
        idoit_enabled: idoitConfig.idoit_enabled,
        idoit_base_url: idoitConfig.idoit_base_url,
        idoit_jsonrpc_path: idoitConfig.idoit_jsonrpc_path,
        idoit_portal_url: idoitConfig.idoit_portal_url,
        idoit_timeout_seconds: idoitConfig.idoit_timeout_seconds,
        idoit_basic_username: idoitConfig.idoit_basic_username,
        idoit_default_object_type: idoitConfig.idoit_default_object_type,
        idoit_auto_sync_enabled: idoitConfig.idoit_auto_sync_enabled,
        idoit_sync_scope: idoitConfig.idoit_sync_scope,
        idoit_create_policy: idoitConfig.idoit_create_policy,
        idoit_sync_interval_minutes: idoitConfig.idoit_sync_interval_minutes,
        idoit_offline_retire_days: idoitConfig.idoit_offline_retire_days,
        idoit_sync_status_field: idoitConfig.idoit_sync_status_field,
        idoit_mapping_json: idoitConfig.idoit_mapping_raw,
        ...(idoitApiKey ? { idoit_api_key: idoitApiKey } : {}),
        ...(idoitBasicPassword ? { idoit_basic_password: idoitBasicPassword } : {}),
      })
      setIdoitTestError(null)
      if (result.message) {
        toast.success(String(result.message))
      } else {
        toast.success(t('idoit_connection_success'))
      }
    } catch (error) {
      const details = extractIdoitErrorDetails(error)
      setIdoitTestError(details)
      toast.error(details.message || t('idoit_connection_failed'))
    } finally {
      setIdoitTesting(false)
    }
  }

  async function testIdoitMapping() {
    setIdoitTesting(true)
    try {
      const result = await idoitApi.testMapping()
      if (result.ok === false) {
        toast.error(t('idoit_mapping_has_errors'))
      } else {
        toast.success(t('idoit_mapping_valid'))
      }
    } catch {
      toast.error(t('idoit_mapping_test_failed'))
    } finally {
      setIdoitTesting(false)
    }
  }

  function updateIdoitMapping(updater: (mapping: IdoitMapping) => IdoitMapping) {
    if (!idoitConfig || !idoitMappingState.mapping) return
    setIdoitConfig({
      ...idoitConfig,
      idoit_mapping_raw: stringifyIdoitMapping(updater(idoitMappingState.mapping)),
    })
  }

  function updateIdoitFieldMapping(sourceField: string, targetField: string) {
    updateIdoitMapping((mapping) => {
      const fields = { ...(mapping.fields || {}) }
      const trimmed = targetField.trim()
      if (trimmed) {
        fields[sourceField] = trimmed
      } else {
        delete fields[sourceField]
      }
      return { ...mapping, fields }
    })
  }

  function updateIdoitIdentityField(identityField: 'externalIdField' | 'syncStatusField', targetField: string) {
    updateIdoitMapping((mapping) => ({
      ...mapping,
      identity: {
        ...(mapping.identity || {}),
        [identityField]: targetField.trim(),
      },
    }))
  }

  async function syncAllIdoitDevices() {
    setIdoitSyncingAll(true)
    setIdoitSyncProgress(null)
    try {
      const deviceResult = await devicesApi.list()
      const registeredDevices = deviceResult.items.filter((device) => device.is_registered && (idoitConfig?.idoit_sync_scope !== 'manual' || device.idoit_sync_enabled !== false))
      const total = registeredDevices.length
      let success = 0
      let failure = 0
      let skipped = 0

      if (total === 0) {
        toast.success(t('idoit_bulk_sync_success', { success: '0', failure: '0', skipped: '0' }))
        return
      }

      for (let index = 0; index < registeredDevices.length; index += 1) {
        const device = registeredDevices[index]
        const label = device.label || device.hostname || device.ip_address || device.mac_address
        setIdoitSyncProgress({ current: index + 1, total, success, failure, skipped, label })
        try {
          const result = await idoitApi.syncDevice(device.id)
          if (result.skipped) {
            skipped += 1
          } else {
            success += 1
          }
        } catch {
          failure += 1
        }
        setIdoitSyncProgress({ current: index + 1, total, success, failure, skipped, label })
      }

      setIdoitTestError(null)
      toast.success(t('idoit_bulk_sync_success', { success: String(success), failure: String(failure), skipped: String(skipped) }))
      loadIdoitConfig().catch(() => {})
      loadIdoitLogs().catch(() => {})
    } catch (error) {
      const details = extractIdoitErrorDetails(error)
      setIdoitTestError(details)
      toast.error(details.message || t('idoit_sync_failed'))
    } finally {
      setIdoitSyncingAll(false)
      setIdoitSyncProgress(null)
    }
  }

  async function enableIdoitSyncForAllDevices() {
    setIdoitEnablingAll(true)
    try {
      const result = await idoitApi.enableSyncAll()
      toast.success(t('idoit_enable_sync_all_success', {
        updated: String(result.updated),
        total: String(result.total),
      }))
    } catch (error) {
      const details = extractIdoitErrorDetails(error)
      setIdoitTestError(details)
      toast.error(details.message || t('idoit_enable_sync_all_failed'))
    } finally {
      setIdoitEnablingAll(false)
    }
  }

  async function saveUi() {
    setSaving(true)
    try {
      await settingsApi.updateUi(
        current.advanced_view_enabled,
        current.show_cmdb_integrations,
        current.show_services_nav,
        current.show_dhcp_monitor_nav,
        current.show_plugin_api,
        current.show_passive_discovery,
        current.show_mdns_discovery,
        current.show_ssdp_discovery,
        current.show_tls_checks,
        current.show_ping_history,
        current.show_build_info,
      )
      setAdvancedViewEnabled(current.advanced_view_enabled)
      setShowCmdbIntegrations(current.advanced_view_enabled && current.show_cmdb_integrations)
      setShowServicesNav(current.advanced_view_enabled && current.show_services_nav)
      setShowDhcpMonitorNav(current.advanced_view_enabled && current.show_dhcp_monitor_nav)
      setShowPluginApi(current.advanced_view_enabled && current.show_plugin_api)
      setShowPassiveDiscovery(current.advanced_view_enabled && current.show_passive_discovery)
      setShowMdnsDiscovery(current.advanced_view_enabled && current.show_mdns_discovery)
      setShowSsdpDiscovery(current.advanced_view_enabled && current.show_ssdp_discovery)
      setShowTlsChecks(current.advanced_view_enabled && current.show_tls_checks)
      setShowPingHistory(current.advanced_view_enabled && current.show_ping_history)
      setShowBuildInfo(current.show_build_info)
      toast.success(t('ui_settings_saved'))
    } catch {
      toast.error(t('ui_settings_save_failed'))
    } finally {
      setSaving(false)
    }
  }

  const settingSections = [
    { key: 'system' as const, label: t('system') },
    { key: 'features' as const, label: t('feature_visibility_tab') },
    { key: 'database' as const, label: t('database') },
    { key: 'network' as const, label: t('network_discovery') },
    { key: 'notifications' as const, label: t('notifications') },
    { key: 'inventory' as const, label: t('inventory_tools_title') },
    { key: 'backup' as const, label: t('backup_restore') },
    ...(current.advanced_view_enabled && current.show_cmdb_integrations ? [{ key: 'cmdb' as const, label: t('cmdb_tab') }] : []),
  ]

  const featureGroups = [
    {
      id: 'core',
      title: t('feature_category_core'),
      description: t('feature_category_core_hint'),
      items: [
        {
          key: 'advanced',
          checked: current.advanced_view_enabled,
          label: t('advanced_view_enabled'),
          description: t('advanced_view_enabled_hint'),
          onChange: (checked: boolean) => setSettings({
            ...current,
            advanced_view_enabled: checked,
            show_cmdb_integrations: checked ? current.show_cmdb_integrations : false,
            show_services_nav: checked ? current.show_services_nav : false,
            show_dhcp_monitor_nav: checked ? current.show_dhcp_monitor_nav : false,
            show_plugin_api: checked ? current.show_plugin_api : false,
            show_passive_discovery: checked ? current.show_passive_discovery : false,
            show_mdns_discovery: checked ? current.show_mdns_discovery : false,
            show_ssdp_discovery: checked ? current.show_ssdp_discovery : false,
            show_tls_checks: checked ? current.show_tls_checks : false,
            show_ping_history: checked ? current.show_ping_history : false,
          }),
        },
        {
          key: 'build-info',
          checked: current.show_build_info,
          label: t('show_build_info'),
          description: t('show_build_info_hint'),
          onChange: (checked: boolean) => setSettings({ ...current, show_build_info: checked }),
        },
      ],
    },
    {
      id: 'monitoring',
      title: t('feature_category_monitoring'),
      description: t('feature_category_monitoring_hint'),
      items: [
        {
          key: 'tls',
          checked: current.show_tls_checks,
          disabled: !current.advanced_view_enabled,
          label: t('show_tls_checks'),
          description: t('show_tls_checks_hint'),
          onChange: (checked: boolean) => setSettings({ ...current, show_tls_checks: checked }),
        },
        {
          key: 'ping-history',
          checked: current.show_ping_history,
          disabled: !current.advanced_view_enabled,
          label: t('show_ping_history'),
          description: t('show_ping_history_hint'),
          onChange: (checked: boolean) => setSettings({ ...current, show_ping_history: checked }),
        },
        {
          key: 'dhcp-monitor',
          checked: current.show_dhcp_monitor_nav,
          disabled: !current.advanced_view_enabled,
          label: t('show_dhcp_monitor_nav'),
          description: t('show_dhcp_monitor_nav_hint'),
          onChange: (checked: boolean) => setSettings({ ...current, show_dhcp_monitor_nav: checked }),
        },
      ],
    },
    {
      id: 'extensions',
      title: t('feature_category_extensions'),
      description: t('feature_category_extensions_hint'),
      items: [
        {
          key: 'plugin-api',
          checked: current.show_plugin_api,
          disabled: !current.advanced_view_enabled,
          label: t('show_plugin_api'),
          description: t('show_plugin_api_hint'),
          onChange: (checked: boolean) => setSettings({
            ...current,
            show_plugin_api: checked,
            show_passive_discovery: checked ? current.show_passive_discovery : false,
            show_mdns_discovery: checked ? current.show_mdns_discovery : false,
            show_ssdp_discovery: checked ? current.show_ssdp_discovery : false,
          }),
        },
        {
          key: 'passive-discovery',
          checked: current.show_passive_discovery,
          disabled: !current.advanced_view_enabled || !current.show_plugin_api,
          label: t('show_passive_discovery'),
          description: t('show_passive_discovery_hint'),
          onChange: (checked: boolean) => setSettings({
            ...current,
            show_passive_discovery: checked,
            show_mdns_discovery: checked ? current.show_mdns_discovery : false,
            show_ssdp_discovery: checked ? current.show_ssdp_discovery : false,
          }),
        },
        {
          key: 'mdns-discovery',
          checked: current.show_mdns_discovery,
          disabled: !current.advanced_view_enabled || !current.show_plugin_api || !current.show_passive_discovery,
          label: t('show_mdns_discovery'),
          description: t('show_mdns_discovery_hint'),
          onChange: (checked: boolean) => setSettings({ ...current, show_mdns_discovery: checked }),
        },
        {
          key: 'ssdp-discovery',
          checked: current.show_ssdp_discovery,
          disabled: !current.advanced_view_enabled || !current.show_plugin_api || !current.show_passive_discovery,
          label: t('show_ssdp_discovery'),
          description: t('show_ssdp_discovery_hint'),
          onChange: (checked: boolean) => setSettings({ ...current, show_ssdp_discovery: checked }),
        },
      ],
    },
    {
      id: 'inventory',
      title: t('feature_category_inventory'),
      description: t('feature_category_inventory_hint'),
      items: [
        {
          key: 'services',
          checked: current.show_services_nav,
          disabled: !current.advanced_view_enabled,
          label: t('show_services_nav'),
          description: t('show_services_nav_hint'),
          onChange: (checked: boolean) => setSettings({ ...current, show_services_nav: checked }),
        },
        {
          key: 'cmdb',
          checked: current.show_cmdb_integrations,
          disabled: !current.advanced_view_enabled,
          label: t('show_cmdb_integrations'),
          description: t('show_cmdb_integrations_hint'),
          onChange: (checked: boolean) => setSettings({ ...current, show_cmdb_integrations: checked }),
        },
      ],
    },
  ]

  return (
    <div className="space-y-6">
      <div className="flex gap-2 overflow-x-auto rounded-xl border border-border bg-surface p-1">
        {settingSections.map((section) => (
          <button
            key={section.key}
            onClick={() => setActiveSection(section.key)}
            className={`px-3 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-colors ${activeSection === section.key ? 'bg-primary-dim text-primary' : 'text-text-muted hover:text-text-base hover:bg-surface2'}`}
          >
            {section.label}
          </button>
        ))}
      </div>

      {/* ── SYSTEM ────────────────────────────────────────────────────────── */}
      {activeSection === 'system' && (
      <div>
        <h2 className="text-xs font-semibold text-text-subtle uppercase tracking-widest mb-3">
          {t('system')}
        </h2>
        <div className="space-y-4">
          <Card>
            <div className="flex items-center justify-between gap-4 mb-4">
              <div>
                <h2 className="text-lg font-semibold text-text-base">LanLens</h2>
                <p className="text-sm text-text-subtle">
                  {t('general_instance_settings')}
                </p>
              </div>
              <Button onClick={checkForUpdates} loading={checkingUpdate}>
                {t('check_updates_now')}
              </Button>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label className="block text-sm text-text-subtle mb-1">
                  {t('language')}
                </label>
                <select
                  className="input-field"
                  value={lang}
                  onChange={(e) => setLang(e.target.value as typeof lang)}
                >
                  <option value="en">English</option>
                  <option value="de">Deutsch</option>
                  <option value="it">Italiano</option>
                  <option value="zh">中文</option>
                </select>
              </div>

              <div>
                <label className="block text-sm text-text-subtle mb-1">Server URL</label>
                <Input
                  value={current.server_url}
                  onChange={(e) => setSettings({ ...current, server_url: e.target.value })}
                  placeholder="https://lanlens.example.com"
                />
              </div>
            </div>

            <div className="mt-4">
              <Button onClick={saveServerUrl} loading={saving}>{t('save_changes')}</Button>
            </div>
          </Card>

          <Card>
            <div className="flex items-start justify-between gap-4 mb-4">
              <div>
                <h2 className="text-lg font-semibold text-text-base">{t('https_settings')}</h2>
                <p className="text-sm text-text-subtle">{t('https_settings_description')}</p>
              </div>
              <span className={`rounded-full px-2 py-1 text-xs ${current.https_configured ? 'bg-success/10 text-success' : 'bg-surface2 text-text-subtle'}`}>
                {current.https_configured ? t('certificate_configured') : t('certificate_missing')}
              </span>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="flex items-center gap-2 text-sm text-text-base">
                <input
                  type="checkbox"
                  checked={current.https_enabled}
                  onChange={(e) => setSettings({ ...current, https_enabled: e.target.checked })}
                />
                {t('enable_https')}
              </label>
              <label className="flex items-center gap-2 text-sm text-text-base">
                <input
                  type="checkbox"
                  checked={current.https_redirect_http}
                  onChange={(e) => setSettings({ ...current, https_redirect_http: e.target.checked })}
                />
                {t('redirect_http_to_https')}
              </label>

              <div>
                <label className="block text-sm text-text-subtle mb-1">{t('https_port')}</label>
                <Input
                  type="number"
                  min="1"
                  max="65535"
                  value={String(current.https_port)}
                  onChange={(e) => setSettings({ ...current, https_port: Number(e.target.value) || 7765 })}
                />
                <p className="mt-1 text-xs text-text-subtle">{t('https_port_hint')}</p>
              </div>
            </div>

            <div className="mt-4 grid gap-4 md:grid-cols-3">
              <div>
                <label className="block text-sm text-text-subtle mb-1">{t('certificate_file')}</label>
                <input
                  className="block w-full text-sm text-text-muted file:mr-3 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-2 file:text-sm file:font-medium file:text-white"
                  type="file"
                  accept=".crt,.cer,.pem"
                  onChange={(e) => setHttpsCertificate(e.target.files?.[0] || null)}
                />
              </div>
              <div>
                <label className="block text-sm text-text-subtle mb-1">{t('private_key_file')}</label>
                <input
                  className="block w-full text-sm text-text-muted file:mr-3 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-2 file:text-sm file:font-medium file:text-white"
                  type="file"
                  accept=".key,.pem"
                  onChange={(e) => setHttpsPrivateKey(e.target.files?.[0] || null)}
                />
              </div>
              <div>
                <label className="block text-sm text-text-subtle mb-1">{t('ca_chain_file')}</label>
                <input
                  className="block w-full text-sm text-text-muted file:mr-3 file:rounded-md file:border-0 file:bg-surface2 file:px-3 file:py-2 file:text-sm file:font-medium file:text-text-base"
                  type="file"
                  accept=".crt,.cer,.pem"
                  onChange={(e) => setHttpsCaChain(e.target.files?.[0] || null)}
                />
              </div>
            </div>

            <p className="mt-3 text-xs text-text-subtle">{t('https_upload_hint')}</p>
            <div className="mt-4">
              <Button onClick={saveHttpsSettings} loading={saving}>{t('save_https_settings')}</Button>
            </div>
          </Card>

        </div>
      </div>
      )}

      {/* ── FEATURE VISIBILITY ───────────────────────────────────────────── */}
      {activeSection === 'features' && (
      <div>
        <h2 className="text-xs font-semibold text-text-subtle uppercase tracking-widest mb-3">
          {t('feature_visibility_tab')}
        </h2>
        <div className="space-y-4">
          <div>
            <h2 className="text-lg font-semibold text-text-base mb-1">{t('feature_visibility_title')}</h2>
            <p className="text-sm text-text-subtle">{t('feature_visibility_description')}</p>
          </div>
          {featureGroups.map((group) => (
            <Card key={group.id}>
              <div className="mb-4">
                <h3 className="text-sm font-semibold text-text-base">{group.title}</h3>
                <p className="mt-1 text-xs text-text-subtle">{group.description}</p>
              </div>
              <div className="grid gap-3 lg:grid-cols-2">
                {group.items.map((item) => (
                  <ToggleSwitch
                    key={item.key}
                    checked={item.checked}
                    disabled={'disabled' in item ? item.disabled : false}
                    label={item.label}
                    description={item.description}
                    onChange={item.onChange}
                  />
                ))}
              </div>
            </Card>
          ))}
          <div className="flex justify-end">
            <Button onClick={saveUi} loading={saving}>{t('save_changes')}</Button>
          </div>
        </div>
      </div>
      )}

      {/* ── DATABASE ──────────────────────────────────────────────────────── */}
      {activeSection === 'database' && (
      <div>
        <h2 className="text-xs font-semibold text-text-subtle uppercase tracking-widest mb-3">
          {t('database')}
        </h2>
        <div className="space-y-4">
          <Card>
            <h2 className="text-lg font-semibold text-text-base mb-1">
              {t('database_connection')}
            </h2>
            <p className="text-sm text-text-subtle mb-3">
              {t('sqlite_default_description')}
            </p>
            <div className="bg-surface2 rounded-lg border border-border p-3 space-y-2 text-xs font-mono">
              <p className="text-text-subtle"># docker-compose.yml environment:</p>
              <p className="text-success">DATABASE_URL=mysql+pymysql://user:pass@mariadb:3306/lanlens</p>
            </div>
            <p className="text-xs text-text-subtle mt-3">
              {t('pymysql_hint')}
            </p>
          </Card>
        </div>
      </div>
      )}

      {/* ── NETWORK DISCOVERY ─────────────────────────────────────────────── */}
      {activeSection === 'network' && (
      <div>
        <h2 className="text-xs font-semibold text-text-subtle uppercase tracking-widest mb-3">
          {t('network_discovery')}
        </h2>
        <div className="space-y-4">
          <div>
            <h2 className="text-lg font-semibold text-text-base mb-1">{t('discovery_category_ranges')}</h2>
            <p className="text-sm text-text-subtle">{t('discovery_category_ranges_hint')}</p>
          </div>
          <Card>
            <h2 className="text-lg font-semibold text-text-base mb-2">{t('dhcp_range_title')}</h2>
            <p className="text-sm text-text-subtle mb-4">
              {t('dhcp_tagging_description')}
            </p>
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label className="block text-sm text-text-subtle mb-1">{t('dhcp_start_label')}</label>
                <Input value={current.dhcp_start} onChange={(e) => setSettings({ ...current, dhcp_start: e.target.value })} />
              </div>
              <div>
                <label className="block text-sm text-text-subtle mb-1">{t('dhcp_end_label')}</label>
                <Input value={current.dhcp_end} onChange={(e) => setSettings({ ...current, dhcp_end: e.target.value })} />
              </div>
            </div>
            <div className="mt-4">
              <Button onClick={saveDhcp} loading={saving}>{t('save_changes')}</Button>
            </div>
          </Card>

          <Card>
            <h2 className="text-lg font-semibold text-text-base mb-2">{t('scan_range_title')}</h2>
            <p className="text-sm text-text-subtle mb-4">
              {t('arp_scan_description')}
            </p>
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label className="block text-sm text-text-subtle mb-1">{t('scan_start_label')}</label>
                <Input value={current.scan_start} onChange={(e) => setSettings({ ...current, scan_start: e.target.value })} />
              </div>
              <div>
                <label className="block text-sm text-text-subtle mb-1">{t('scan_end_label')}</label>
                <Input value={current.scan_end} onChange={(e) => setSettings({ ...current, scan_end: e.target.value })} />
              </div>
            </div>
            <div className="mt-4">
              <label className="block text-sm text-text-subtle mb-1">{t('additional_scan_targets_label')}</label>
              <textarea
                className="w-full min-h-24 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text-base focus:outline-none focus:ring-2 focus:ring-primary/40"
                value={current.scan_additional_targets || ''}
                onChange={(e) => setSettings({ ...current, scan_additional_targets: e.target.value })}
                placeholder="192.168.10.0/24\n10.10.0.0/24"
              />
              <p className="mt-2 text-xs text-text-subtle">{t('additional_scan_targets_hint')}</p>
            </div>
            <div className="mt-4">
              <Button onClick={saveScanRange} loading={saving}>{t('save_changes')}</Button>
            </div>
          </Card>

          <div className="pt-2">
            <h2 className="text-lg font-semibold text-text-base mb-1">{t('discovery_category_monitoring')}</h2>
            <p className="text-sm text-text-subtle">{t('discovery_category_monitoring_hint')}</p>
          </div>

          <Card>
            <div className="flex flex-col gap-4">
              <div>
                <h2 className="text-lg font-semibold text-text-base">{t('ping_monitor_title')}</h2>
                <p className="text-sm text-text-subtle">{t('ping_monitor_description')}</p>
              </div>
              <label className="flex items-start gap-3 rounded-lg border border-border bg-surface2/35 p-3">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={current.ping_monitor_enabled}
                  onChange={(e) => setSettings({ ...current, ping_monitor_enabled: e.target.checked })}
                />
                <span>
                  <span className="block text-sm font-medium text-text-base">{t('ping_monitor_background')}</span>
                  <span className="block text-xs text-text-subtle">{t('ping_monitor_background_hint')}</span>
                </span>
              </label>
              <div className="grid gap-3 md:grid-cols-2">
                <div>
                  <label className="block text-sm text-text-subtle mb-1">{t('ping_monitor_interval')}</label>
                  <Input
                    type="number"
                    value={String(current.ping_monitor_interval_minutes)}
                    onChange={(e) => setSettings({ ...current, ping_monitor_interval_minutes: Number(e.target.value) || 5 })}
                  />
                </div>
              </div>
              <div>
                <Button onClick={savePingMonitorSchedule} loading={saving}>{t('ping_monitor_save')}</Button>
              </div>
            </div>
          </Card>

          <div className="pt-2">
            <h2 className="text-lg font-semibold text-text-base mb-1">{t('discovery_category_multicast')}</h2>
            <p className="text-sm text-text-subtle">{t('discovery_category_multicast_hint')}</p>
          </div>

          {current.advanced_view_enabled && current.show_plugin_api && current.show_passive_discovery && (
          <Card>
            <div className="flex flex-col gap-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="text-lg font-semibold text-text-base">{t('multicast_discovery_capture')}</h2>
                  <p className="text-sm text-text-subtle">
                    {t('multicast_discovery_capture_hint')}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button variant="outline" onClick={runPassiveDiscoveryDiagnostics} loading={passiveDiagnosticLoading}>
                    {t('multicast_discovery_diagnostics_10s')}
                  </Button>
                  <Button variant="outline" onClick={startPassiveDiscoveryCapture} loading={passiveCaptureLoading}>
                    {t('multicast_discovery_capture_30s')}
                  </Button>
                </div>
              </div>
              {passiveCaptureReport && (
                <div className="rounded-lg border border-border bg-surface2/35 p-3 text-xs text-text-subtle">
                  <div className="mb-2 font-medium text-text-muted">{t('multicast_discovery_last_diagnostic')}</div>
                  <div className="grid gap-2 md:grid-cols-3">
                    <div>{t('multicast_discovery_packets_seen')}: <span className="text-text-base">{passiveCaptureReport.packets_seen}</span></div>
                    <div>{t('multicast_discovery_packets_parsed')}: <span className="text-text-base">{passiveCaptureReport.packets_parsed}</span></div>
                    <div>{t('multicast_discovery_observations_stored')}: <span className="text-text-base">{passiveCaptureReport.observations_stored}</span></div>
                    <div>{t('multicast_discovery_duplicates')}: <span className="text-text-base">{passiveCaptureReport.duplicates_skipped}</span></div>
                    <div>{t('multicast_discovery_protocols')}: <span className="text-text-base">{passiveCaptureReport.protocols.join(', ')}</span></div>
                    <div>{t('multicast_discovery_filter')}: <span className="text-text-base">{passiveCaptureReport.filter || '-'}</span></div>
                  </div>
                  {passiveCaptureReport.errors.length > 0 && (
                    <div className="mt-2 text-danger">{passiveCaptureReport.errors.join(' · ')}</div>
                  )}
                </div>
              )}
              <div className="rounded-lg border border-border bg-surface2/35 p-3">
                <label className="flex items-start gap-3">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={current.passive_discovery_background_enabled}
                    onChange={(e) => setSettings({ ...current, passive_discovery_background_enabled: e.target.checked })}
                  />
                  <span>
                    <span className="block text-sm font-medium text-text-base">{t('multicast_discovery_background')}</span>
                    <span className="block text-xs text-text-subtle">
                      {t('multicast_discovery_background_hint')}
                    </span>
                  </span>
                </label>
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <div>
                    <label className="block text-sm text-text-subtle mb-1">{t('multicast_discovery_interval')}</label>
                    <Input
                      type="number"
                      value={String(current.passive_discovery_interval_minutes)}
                      onChange={(e) => setSettings({ ...current, passive_discovery_interval_minutes: Number(e.target.value) || 15 })}
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-text-subtle mb-1">{t('multicast_discovery_duration')}</label>
                    <Input
                      type="number"
                      value={String(current.passive_discovery_capture_seconds)}
                      onChange={(e) => setSettings({ ...current, passive_discovery_capture_seconds: Number(e.target.value) || 30 })}
                    />
                  </div>
                </div>
                <div className="mt-3">
                  <Button onClick={savePassiveDiscoverySchedule} loading={saving}>{t('multicast_discovery_save_background')}</Button>
                </div>
              </div>
              <div className="grid gap-2 text-xs text-text-subtle md:grid-cols-3">
                <div className="rounded-lg border border-border bg-surface2/40 p-3">{t('multicast_discovery_mdns_hint')}</div>
                <div className="rounded-lg border border-border bg-surface2/40 p-3">{t('multicast_discovery_ssdp_hint')}</div>
                <div className="rounded-lg border border-border bg-surface2/40 p-3">{t('multicast_discovery_control_hint')}</div>
              </div>
            </div>
          </Card>
          )}

          {current.advanced_view_enabled && false && (
          <Card>
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold text-text-base">Multicast discovery capture</h2>
                <p className="text-sm text-text-subtle">
                  Captures visible mDNS, SSDP/UPnP and multicast control-plane packets for 30 seconds. Linked results appear on matching device detail pages.
                </p>
              </div>
              <Button variant="outline" onClick={startPassiveDiscoveryCapture} loading={passiveCaptureLoading}>
                Capture 30s
              </Button>
            </div>
            <div className="mt-3 grid gap-2 text-xs text-text-subtle md:grid-cols-3">
              <div className="rounded-lg border border-border bg-surface2/40 p-3">mDNS: UDP/5353 Bonjour names and services.</div>
              <div className="rounded-lg border border-border bg-surface2/40 p-3">SSDP/UPnP: UDP/1900 device and service advertisements.</div>
              <div className="rounded-lg border border-border bg-surface2/40 p-3">Multicast: OSPF, VRRP and HSRP control-plane hints.</div>
            </div>
          </Card>
          )}

          <div className="pt-2">
            <h2 className="text-lg font-semibold text-text-base mb-1">{t('discovery_category_remote')}</h2>
            <p className="text-sm text-text-subtle">{t('discovery_category_remote_hint')}</p>
          </div>

          {current.advanced_view_enabled && (
          <Card>
            <div className="flex items-start justify-between gap-4 mb-4">
              <div>
                <h2 className="text-lg font-semibold text-text-base mb-1">Scan Nodes</h2>
                <p className="text-sm text-text-subtle">Optionale Scanner pro VLAN oder Standort. Die Nodes melden ausgehend an diese zentrale LanLens-Instanz.</p>
              </div>
              <Button variant="outline" onClick={loadScanNodes} loading={scanNodesLoading}>Aktualisieren</Button>
            </div>

            <div className="grid gap-3 md:grid-cols-3">
              <Input placeholder="Name, z.B. vlan-20-hamburg" value={scanNodeName} onChange={(e) => setScanNodeName(e.target.value)} />
              <Input placeholder="Standort, z.B. Hamburg" value={scanNodeSite} onChange={(e) => setScanNodeSite(e.target.value)} />
              <Input placeholder="Segment/VLAN, z.B. VLAN 20" value={scanNodeSegment} onChange={(e) => setScanNodeSegment(e.target.value)} />
            </div>
            <div className="mt-3">
              <Button onClick={createScanNode} loading={scanNodesLoading}>Einzeiler generieren</Button>
            </div>

            {scanNodeProvisioning && (
              <div className="mt-4 rounded-lg border border-primary/30 bg-primary-dim/20 p-3">
                <div className="flex items-center justify-between gap-3 mb-2">
                  <p className="text-sm font-medium text-text-base">Einmaliger Install-Befehl fuer {scanNodeProvisioning.name}</p>
                  <Button size="sm" variant="outline" onClick={copyScanNodeCommand}>Kopieren</Button>
                </div>
                <pre className="overflow-auto whitespace-pre-wrap break-all rounded bg-background p-3 text-xs text-text-muted">{scanNodeProvisioning.install_command}</pre>
                <p className="mt-2 text-xs text-text-subtle">Der Token wird nur jetzt angezeigt. Bei Verlust Token rotieren und den Node neu starten.</p>
              </div>
            )}

            <div className="mt-4 overflow-auto rounded-lg border border-border">
              <table className="min-w-full text-left text-xs">
                <thead className="bg-surface2 text-text-subtle">
                  <tr>
                    <th className="px-3 py-2 font-medium">Name</th>
                    <th className="px-3 py-2 font-medium">Standort</th>
                    <th className="px-3 py-2 font-medium">Segment</th>
                    <th className="px-3 py-2 font-medium">Status</th>
                    <th className="px-3 py-2 font-medium">Zuletzt gesehen</th>
                    <th className="px-3 py-2 font-medium">Aktionen</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {scanNodes.length === 0 ? (
                    <tr><td className="px-3 py-3 text-text-subtle" colSpan={6}>Noch keine Scan Nodes eingerichtet.</td></tr>
                  ) : scanNodes.map((node) => (
                    <tr key={node.id}>
                      <td className="px-3 py-2 font-medium text-text-base">{node.name}</td>
                      <td className="px-3 py-2 text-text-muted">{node.site || '—'}</td>
                      <td className="px-3 py-2 text-text-muted">{node.segment_label || '—'}</td>
                      <td className="px-3 py-2 text-text-muted">{node.status}</td>
                      <td className="px-3 py-2 text-text-muted">{node.last_seen ? formatDateTime(node.last_seen) : '—'}</td>
                      <td className="px-3 py-2">
                        <div className="flex gap-2">
                          <Button size="sm" variant="outline" onClick={() => rotateScanNodeToken(node.id)}>Token</Button>
                          <Button size="sm" variant="danger" onClick={() => deleteScanNode(node.id)}>Loeschen</Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          )}

          {current.advanced_view_enabled && (
          <Card>
            <div className="flex items-start justify-between gap-4 mb-4">
              <div>
                <h2 className="text-lg font-semibold text-text-base">{t('snmp_topology_title')}</h2>
                <p className="text-sm text-text-subtle">{t('snmp_topology_description')}</p>
              </div>
              <Button variant="outline" onClick={loadSnmp} loading={snmpLoading}>{t('refresh')}</Button>
            </div>

            <div className="grid gap-3 md:grid-cols-4">
              <Input placeholder={t('snmp_profile_name')} value={snmpProfileName} onChange={(e) => setSnmpProfileName(e.target.value)} />
              <select className="input-field" value={snmpVersion} onChange={(e) => setSnmpVersion(e.target.value as SnmpProfileCreate['version'])}>
                <option value="1">{t('snmp_version_1')}</option>
                <option value="2c">{t('snmp_version_2c')}</option>
                <option value="3">{t('snmp_version_3')}</option>
              </select>
              {snmpVersion === '3' ? (
                <>
                  <Input placeholder={t('snmp_username')} value={snmpUsername} onChange={(e) => setSnmpUsername(e.target.value)} />
                  <select className="input-field" value={snmpSecurityLevel} onChange={(e) => setSnmpSecurityLevel(e.target.value as SnmpProfileCreate['security_level'])}>
                    <option value="noAuthNoPriv">{t('snmp_security_noauth')}</option>
                    <option value="authNoPriv">{t('snmp_security_auth')}</option>
                    <option value="authPriv">{t('snmp_security_authpriv')}</option>
                  </select>
                  {snmpSecurityLevel !== 'noAuthNoPriv' && (
                    <>
                      <select className="input-field" value={snmpAuthProtocol} onChange={(e) => setSnmpAuthProtocol(e.target.value as SnmpProfileCreate['auth_protocol'])}>
                        <option value="SHA">{t('snmp_auth_sha')}</option>
                        <option value="MD5">{t('snmp_auth_md5')}</option>
                      </select>
                      <Input placeholder={t('snmp_auth_password')} type="password" value={snmpAuthPassword} onChange={(e) => setSnmpAuthPassword(e.target.value)} />
                    </>
                  )}
                  {snmpSecurityLevel === 'authPriv' && (
                    <>
                      <select className="input-field" value={snmpPrivacyProtocol} onChange={(e) => setSnmpPrivacyProtocol(e.target.value as SnmpProfileCreate['privacy_protocol'])}>
                        <option value="AES">{t('snmp_privacy_aes')}</option>
                        <option value="DES">{t('snmp_privacy_des')}</option>
                      </select>
                      <Input placeholder={t('snmp_privacy_password')} type="password" value={snmpPrivacyPassword} onChange={(e) => setSnmpPrivacyPassword(e.target.value)} />
                    </>
                  )}
                </>
              ) : (
                <Input placeholder={t('snmp_community')} type="password" value={snmpCommunity} onChange={(e) => setSnmpCommunity(e.target.value)} />
              )}
              <Button onClick={createSnmpProfile} loading={snmpLoading}>{t('snmp_add_profile')}</Button>
            </div>

            <div className="mt-4 overflow-auto rounded-lg border border-border">
              <table className="min-w-full text-left text-xs">
                <thead className="bg-surface2 text-text-subtle">
                  <tr>
                    <th className="px-3 py-2 font-medium">{t('snmp_profile_name')}</th>
                    <th className="px-3 py-2 font-medium">{t('profile')}</th>
                    <th className="px-3 py-2 font-medium">{t('port')}</th>
                    <th className="px-3 py-2 font-medium">{t('actions')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {snmpProfiles.length === 0 ? (
                    <tr><td className="px-3 py-3 text-text-subtle" colSpan={4}>{t('snmp_no_profiles')}</td></tr>
                  ) : snmpProfiles.map((profile) => (
                    <tr key={profile.id}>
                      <td className="px-3 py-2 font-medium text-text-base">{profile.name}</td>
                      <td className="px-3 py-2 text-text-muted">
                        {profile.version === '3' ? t('snmp_version_3') : profile.version === '1' ? t('snmp_version_1') : t('snmp_version_2c')}
                      </td>
                      <td className="px-3 py-2 text-text-muted">{profile.port}</td>
                      <td className="px-3 py-2">
                        <Button size="sm" variant="danger" onClick={() => deleteSnmpProfile(profile)} disabled={snmpLoading}>
                          {t('delete')}
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="mt-4 grid gap-3 md:grid-cols-4">
              <Input placeholder={t('snmp_switch_name')} value={snmpSwitchName} onChange={(e) => setSnmpSwitchName(e.target.value)} />
              <Input placeholder={t('snmp_switch_host')} value={snmpSwitchHost} onChange={(e) => setSnmpSwitchHost(e.target.value)} />
              <select className="input-field" value={snmpProfileId} onChange={(e) => setSnmpProfileId(e.target.value)}>
                <option value="">{t('snmp_select_profile')}</option>
                {snmpProfiles.map((profile) => (
                  <option key={profile.id} value={profile.id}>{profile.name}</option>
                ))}
              </select>
              <Button onClick={createSnmpSwitch} loading={snmpLoading}>{t('snmp_add_switch')}</Button>
            </div>

            <div className="mt-4 overflow-auto rounded-lg border border-border">
              <table className="min-w-full text-left text-xs">
                <thead className="bg-surface2 text-text-subtle">
                  <tr>
                    <th className="px-3 py-2 font-medium">{t('name')}</th>
                    <th className="px-3 py-2 font-medium">{t('snmp_host')}</th>
                    <th className="px-3 py-2 font-medium">{t('snmp_sys_name')}</th>
                    <th className="px-3 py-2 font-medium">{t('vendor')}</th>
                    <th className="px-3 py-2 font-medium">{t('interfaces')}</th>
                    <th className="px-3 py-2 font-medium">{t('snmp_macs')}</th>
                    <th className="px-3 py-2 font-medium">{t('last_seen')}</th>
                    <th className="px-3 py-2 font-medium">{t('actions')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {snmpSwitches.length === 0 ? (
                    <tr><td className="px-3 py-3 text-text-subtle" colSpan={8}>{t('snmp_no_switches')}</td></tr>
                  ) : snmpSwitches.map((item) => (
                    <tr key={item.id}>
                      <td className="px-3 py-2 font-medium text-text-base">
                        <div>{item.name}</div>
                        {item.last_error && <div className="mt-1 max-w-xs text-xs font-normal text-danger">{item.last_error}</div>}
                      </td>
                      <td className="px-3 py-2 text-text-muted">{item.host}</td>
                      <td className="px-3 py-2 text-text-muted">{item.sys_name || '—'}</td>
                      <td className="px-3 py-2 text-text-muted">
                        <div>{item.vendor || '—'}</div>
                        {item.vendor_notes && <div className="mt-1 max-w-xs text-[11px] text-text-subtle">{item.vendor_notes}</div>}
                      </td>
                      <td className="px-3 py-2 text-text-muted">{item.interface_count}</td>
                      <td className="px-3 py-2 text-text-muted">{item.mac_count}</td>
                      <td className="px-3 py-2 text-text-muted">{item.last_poll_at ? formatDateTime(item.last_poll_at) : '—'}</td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <Button size="sm" variant="outline" onClick={() => pollSnmpSwitch(item.id)} disabled={snmpLoading}>{t('poll_now')}</Button>
                          <Button size="sm" variant="danger" onClick={() => deleteSnmpSwitch(item)} disabled={snmpLoading}>{t('delete')}</Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="mt-4 overflow-auto rounded-lg border border-border">
              <table className="min-w-full text-left text-xs">
                <thead className="bg-surface2 text-text-subtle">
                  <tr>
                    <th className="px-3 py-2 font-medium">{t('col_device')}</th>
                    <th className="px-3 py-2 font-medium">{t('mac_address')}</th>
                    <th className="px-3 py-2 font-medium">{t('snmp_switch')}</th>
                    <th className="px-3 py-2 font-medium">{t('port')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {snmpEndpoints.slice(0, 20).map((entry) => (
                    <tr key={`${entry.switch_host}-${entry.mac_address}-${entry.vlan || ''}`}>
                      <td className="px-3 py-2 text-text-muted">{entry.device_label || '—'}</td>
                      <td className="px-3 py-2 text-text-muted">{entry.mac_address}</td>
                      <td className="px-3 py-2 text-text-muted">{entry.switch_name}</td>
                      <td className="px-3 py-2 text-text-muted">{entry.interface_name || entry.if_index || '—'}</td>
                    </tr>
                  ))}
                  {snmpEndpoints.length === 0 && (
                    <tr><td className="px-3 py-3 text-text-subtle" colSpan={4}>{t('snmp_no_endpoints')}</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
          )}

          <div className="pt-2">
            <h2 className="text-lg font-semibold text-text-base mb-1">{t('discovery_category_scan_cadence')}</h2>
            <p className="text-sm text-text-subtle">{t('discovery_category_scan_cadence_hint')}</p>
          </div>

          <Card>
            <h2 className="text-lg font-semibold text-text-base mb-4">{t('scan_schedule_title')}</h2>
            <div>
              <label className="block text-sm text-text-subtle mb-1">{t('interval_minutes')}</label>
              <Input
                type="number"
                value={String(current.scan_interval_minutes)}
                onChange={(e) => setSettings({ ...current, scan_interval_minutes: Number(e.target.value) || 1 })}
              />
            </div>
            <div className="mt-4">
              <Button onClick={saveSchedule} loading={saving}>{t('save_changes')}</Button>
            </div>
          </Card>

          {current.advanced_view_enabled && (
          <Card>
            <h2 className="text-lg font-semibold text-text-base mb-2">{t('port_scan_range_title')}</h2>
            <p className="text-sm text-text-subtle mb-4">
              {t('port_range_examples')}
            </p>
            <div>
              <label className="block text-sm text-text-subtle mb-1">
                {t('port_range_list')}
              </label>
              <Input
                value={current.port_scan_range}
                onChange={(e) => setSettings({ ...current, port_scan_range: e.target.value })}
                placeholder="top:1000"
              />
            </div>
            <div className="mt-4">
              <Button onClick={savePortScanSettings} loading={saving}>{t('save_changes')}</Button>
            </div>
          </Card>
          )}
        </div>
      </div>
      )}

      {/* ── NOTIFICATIONS ─────────────────────────────────────────────────── */}
      {activeSection === 'notifications' && (
      <div>
        <h2 className="text-xs font-semibold text-text-subtle uppercase tracking-widest mb-3">
          {t('notifications')}
        </h2>
        <div className="space-y-4">
          <Card>
            <h2 className="text-lg font-semibold text-text-base mb-4">Telegram</h2>
            <div className="grid gap-4">
              <div>
                <label className="block text-sm text-text-subtle mb-1">{t('telegram_bot_token_label')}</label>
                <Input
                  type="password"
                  value={telegramTokenDirty ? current.telegram_bot_token : ''}
                  placeholder={current.telegram_bot_token ? t('telegram_token_stored_placeholder') : t('telegram_token_new_placeholder')}
                  onChange={(e) => {
                    setTelegramTokenDirty(true)
                    setSettings({ ...current, telegram_bot_token: e.target.value })
                  }}
                />
                {!telegramTokenDirty && current.telegram_bot_token && (
                  <p className="mt-1 text-xs text-text-subtle">{t('telegram_token_masked_hint')}</p>
                )}
              </div>
              <div>
                <label className="block text-sm text-text-subtle mb-1">{t('telegram_chat_id_label')}</label>
                <Input
                  value={current.telegram_chat_id}
                  onChange={(e) => setSettings({ ...current, telegram_chat_id: e.target.value })}
                />
              </div>
              <label className="flex items-center gap-2 text-sm text-text-base">
                <input
                  type="checkbox"
                  checked={current.telegram_enabled}
                  onChange={(e) => setSettings({ ...current, telegram_enabled: e.target.checked })}
                />
                {t('enable_telegram_notifications')}
              </label>
              <label className="flex items-center gap-2 text-sm text-text-base">
                <input
                  type="checkbox"
                  checked={current.notify_telegram_update}
                  onChange={(e) => setSettings({ ...current, notify_telegram_update: e.target.checked })}
                />
                {t('send_update_notifications')}
              </label>
              <label className="flex items-center gap-2 text-sm text-text-base">
                <input
                  type="checkbox"
                  checked={current.notify_on_new_device}
                  onChange={(e) => setSettings({ ...current, notify_on_new_device: e.target.checked })}
                />
                {t('notify_on_new_device')}
              </label>
              <p className="text-xs text-text-subtle">{t('notify_on_new_device_hint')}</p>
            </div>
            <div className="mt-4 flex gap-3">
              <Button onClick={saveTelegram} loading={saving}>{t('save_changes')}</Button>
              <Button onClick={testTelegram} variant="outline">{t('test_telegram')}</Button>
            </div>
          </Card>


          <Card>
            <h2 className="text-lg font-semibold text-text-base mb-4">
              {t('notifications_webhook')}
            </h2>
            <div className="grid gap-4">
              <div>
                <label className="block text-sm text-text-subtle mb-1">
                  {t('webhook_url_label')}
                </label>
                <Input
                  value={current.webhook_url}
                  onChange={(e) => setSettings({ ...current, webhook_url: e.target.value })}
                  placeholder="https://gotify.example.com/message?token=..."
                />
                <p className="mt-1 text-xs text-text-subtle">{t('webhook_url_hint')}</p>
              </div>
              <label className="flex items-center gap-2 text-sm text-text-base">
                <input
                  type="checkbox"
                  checked={current.webhook_enabled}
                  onChange={(e) => setSettings({ ...current, webhook_enabled: e.target.checked })}
                />
                {t('enable_webhook_notifications')}
              </label>
            </div>
            <div className="mt-4 flex gap-3">
              <Button onClick={saveWebhook} loading={saving}>{t('save_changes')}</Button>
              <Button onClick={testWebhook} variant="outline">
                {t('test_webhook')}
              </Button>
            </div>
          </Card>

          <Card>
            <h2 className="text-lg font-semibold text-text-base mb-4">
              {t('notifications_email')}
            </h2>
            <div className="grid gap-4">
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <label className="block text-sm text-text-subtle mb-1">
                    {t('smtp_host_label')}
                  </label>
                  <Input
                    value={current.smtp_host}
                    onChange={(e) => setSettings({ ...current, smtp_host: e.target.value })}
                    placeholder="smtp.example.com"
                  />
                </div>
                <div>
                  <label className="block text-sm text-text-subtle mb-1">Port</label>
                  <Input
                    type="number"
                    value={String(current.smtp_port)}
                    onChange={(e) => setSettings({ ...current, smtp_port: Number(e.target.value) || 587 })}
                  />
                </div>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <label className="block text-sm text-text-subtle mb-1">
                    {t('username')}
                  </label>
                  <Input
                    value={current.smtp_username}
                    onChange={(e) => setSettings({ ...current, smtp_username: e.target.value })}
                    placeholder="user@example.com"
                  />
                </div>
                <div>
                  <label className="block text-sm text-text-subtle mb-1">
                    {t('password')}
                  </label>
                  <Input
                    type="password"
                    value={current.smtp_password}
                    onChange={(e) => setSettings({ ...current, smtp_password: e.target.value })}
                    placeholder="••••••••"
                  />
                </div>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <label className="block text-sm text-text-subtle mb-1">
                    {t('from_email')}
                  </label>
                  <Input
                    value={current.smtp_from_email}
                    onChange={(e) => setSettings({ ...current, smtp_from_email: e.target.value })}
                    placeholder="lanlens@example.com"
                  />
                </div>
                <div>
                  <label className="block text-sm text-text-subtle mb-1">
                    {t('to_email')}
                  </label>
                  <Input
                    value={current.smtp_to_email}
                    onChange={(e) => setSettings({ ...current, smtp_to_email: e.target.value })}
                    placeholder="admin@example.com"
                  />
                </div>
              </div>
              <label className="flex items-center gap-2 text-sm text-text-base">
                <input
                  type="checkbox"
                  checked={current.smtp_enabled}
                  onChange={(e) => setSettings({ ...current, smtp_enabled: e.target.checked })}
                />
                {t('enable_email_notifications')}
              </label>
              <label className="flex items-center gap-2 text-sm text-text-base">
                <input
                  type="checkbox"
                  checked={current.smtp_use_tls}
                  onChange={(e) => setSettings({ ...current, smtp_use_tls: e.target.checked })}
                />
                {t('use_starttls')}
              </label>
            </div>
            <div className="mt-4 flex gap-3">
              <Button onClick={saveSmtp} loading={saving}>{t('save_changes')}</Button>
              <Button onClick={testSmtp} variant="outline">
                {t('test_email')}
              </Button>
            </div>
          </Card>

          <IgnoreRulesCard />
        </div>
      </div>
      )}

      {/* ── INVENTORY TOOLS ───────────────────────────────────────────────── */}
      {activeSection === 'inventory' && (
      <div>
        <h2 className="text-xs font-semibold text-text-subtle uppercase tracking-widest mb-3">
          {t('inventory_tools_title')}
        </h2>
        <div className="space-y-4">
          <DocumentationExportCard />
          <DeviceMergeCard />
        </div>
      </div>
      )}

      {/* ── BACKUP / RESTORE ──────────────────────────────────────────────── */}
      {activeSection === 'backup' && (
      <div>
        <h2 className="text-xs font-semibold text-text-subtle uppercase tracking-widest mb-3">
          {t('backup_restore')}
        </h2>
        <div className="space-y-4">
          <Card>
            <h2 className="text-lg font-semibold text-text-base mb-1">
              {t('export_import')}
            </h2>
            <p className="text-sm text-text-subtle mb-4">
              {t('back_up_settings_description')}
            </p>
            <div className="flex flex-wrap gap-3">
              <Button variant="outline" onClick={handleExportSettings}>
                {t('export_settings')}
              </Button>
              <Button variant="outline" onClick={handleExportDatabase}>
                {t('export_database')}
              </Button>
            </div>
            <div className="mt-4 pt-4 border-t border-border space-y-3">
              <p className="text-xs text-text-subtle font-medium uppercase tracking-wide">
                {t('restore')}
              </p>
              <label className="flex items-center gap-3 cursor-pointer group">
                <span className="px-3 py-1.5 text-xs font-medium rounded-lg border border-border bg-surface2 text-text-muted group-hover:text-primary group-hover:border-primary/50 transition-colors">
                  {t('import_settings')}
                </span>
                <input
                  type="file"
                  accept=".json"
                  className="hidden"
                  onChange={handleImportSettings}
                />
              </label>
              <p className="text-xs text-text-subtle">
                {t('database_import_hint')}
              </p>
            </div>
          </Card>
          <SelectiveBackupCard />
        </div>
      </div>
      )}

      {/* ── CMDB / I-DOIT ─────────────────────────────────────────────────── */}
      {activeSection === 'cmdb' && (
      <div>
        <h2 className="text-xs font-semibold text-text-subtle uppercase tracking-widest mb-3">
          {t('cmdb_tab')}
        </h2>
        <div className="space-y-4">
          <Card>
            <h2 className="text-lg font-semibold text-text-base mb-1">{t('cmdb_ids_title')}</h2>
            <p className="text-sm text-text-subtle mb-4">
              {t('cmdb_ids_description')}
            </p>
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label className="block text-sm text-text-subtle mb-1">
                  {t('prefix')}
                </label>
                <Input
                  value={current.cmdb_id_prefix}
                  onChange={(e) => setSettings({ ...current, cmdb_id_prefix: e.target.value.toUpperCase() })}
                  placeholder="DEV"
                  maxLength={20}
                />
              </div>
              <div>
                <label className="block text-sm text-text-subtle mb-1">
                  {t('digits')}
                </label>
                <Input
                  type="number"
                  min={1}
                  max={10}
                  value={String(current.cmdb_id_digits)}
                  onChange={(e) => setSettings({ ...current, cmdb_id_digits: Math.min(10, Math.max(1, Number(e.target.value) || 4)) })}
                />
              </div>
            </div>
            <div className="mt-2 text-xs text-text-subtle">
              {t('preview')}{' '}
              <span className="font-mono text-primary">
                {current.cmdb_id_prefix || 'DEV'}-{'1'.padStart(current.cmdb_id_digits || 4, '0')}
              </span>
            </div>
            <div className="mt-4">
              <Button onClick={saveCmdb} loading={saving}>{t('save_changes')}</Button>
            </div>
          </Card>

          <Card>
            <h2 className="text-lg font-semibold text-text-base mb-1">{t('idoit_integration')}</h2>
            <p className="text-sm text-text-subtle mb-4">
              {t('idoit_integration_description')}
            </p>
            {!idoitConfig ? (
              idoitLoadError ? (
                <div className="rounded-lg border border-danger/40 bg-danger/10 p-4 text-sm text-danger">
                  <p className="mb-3">{t('idoit_settings_load_failed')}</p>
                  <Button onClick={loadIdoitConfig} variant="outline">{t('retry')}</Button>
                </div>
              ) : (
                <div className="py-6"><Spinner /></div>
              )
            ) : (
              <>
                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <label className="block text-sm text-text-subtle mb-1">{t('idoit_base_url')}</label>
                    <Input
                      value={idoitConfig.idoit_base_url}
                      onChange={(e) => setIdoitConfig({ ...idoitConfig, idoit_base_url: e.target.value })}
                      placeholder="https://idoit.example.com"
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-text-subtle mb-1">{t('idoit_jsonrpc_path')}</label>
                    <Input
                      value={idoitConfig.idoit_jsonrpc_path}
                      onChange={(e) => setIdoitConfig({ ...idoitConfig, idoit_jsonrpc_path: e.target.value })}
                      placeholder="/src/jsonrpc.php"
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-text-subtle mb-1">{t('idoit_portal_url')}</label>
                    <Input
                      value={idoitConfig.idoit_portal_url}
                      onChange={(e) => setIdoitConfig({ ...idoitConfig, idoit_portal_url: e.target.value })}
                      placeholder="https://idoit.example.com"
                    />
                    <p className="mt-1 text-xs text-text-subtle">{t('idoit_portal_url_hint')}</p>
                  </div>
                  <div>
                    <label className="block text-sm text-text-subtle mb-1">{t('idoit_api_key')}</label>
                    <Input
                      type="password"
                      value={idoitApiKey}
                      onChange={(e) => setIdoitApiKey(e.target.value)}
                      placeholder={idoitConfig.idoit_api_key_configured ? t('idoit_api_key_keep_placeholder') : t('idoit_api_key_new_placeholder')}
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-text-subtle mb-1">{t('idoit_basic_username')}</label>
                    <Input
                      value={idoitConfig.idoit_basic_username || ''}
                      onChange={(e) => setIdoitConfig({ ...idoitConfig, idoit_basic_username: e.target.value })}
                      placeholder="api-user"
                    />
                    <p className="mt-1 text-xs text-text-subtle">{t('idoit_basic_auth_hint')}</p>
                  </div>
                  <div>
                    <label className="block text-sm text-text-subtle mb-1">{t('idoit_basic_password')}</label>
                    <Input
                      type="password"
                      value={idoitBasicPassword}
                      onChange={(e) => setIdoitBasicPassword(e.target.value)}
                      placeholder={idoitConfig.idoit_basic_password_configured ? t('idoit_basic_password_keep_placeholder') : t('idoit_basic_password_new_placeholder')}
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-text-subtle mb-1">{t('idoit_timeout_seconds')}</label>
                    <Input
                      type="number"
                      min={3}
                      max={120}
                      value={String(idoitConfig.idoit_timeout_seconds)}
                      onChange={(e) => setIdoitConfig({ ...idoitConfig, idoit_timeout_seconds: Math.min(120, Math.max(3, Number(e.target.value) || 15)) })}
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-text-subtle mb-1">{t('idoit_default_object_type')}</label>
                    <Input
                      value={idoitConfig.idoit_default_object_type}
                      onChange={(e) => setIdoitConfig({ ...idoitConfig, idoit_default_object_type: e.target.value })}
                      placeholder="C__OBJTYPE__CLIENT"
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-text-subtle mb-1">{t('idoit_sync_status_field')}</label>
                    <Input
                      value={idoitConfig.idoit_sync_status_field}
                      onChange={(e) => setIdoitConfig({ ...idoitConfig, idoit_sync_status_field: e.target.value })}
                      placeholder=""
                    />
                  </div>
                </div>

                <div className="mt-4 grid gap-3">
                  <label className="flex items-center gap-2 text-sm text-text-base">
                    <input
                      type="checkbox"
                      checked={idoitConfig.idoit_enabled}
                      onChange={(e) => setIdoitConfig({ ...idoitConfig, idoit_enabled: e.target.checked })}
                    />
                    {t('enable_idoit_integration')}
                  </label>
                  <label className="flex items-center gap-2 text-sm text-text-base">
                    <input
                      type="checkbox"
                      checked={idoitConfig.idoit_auto_sync_enabled}
                      onChange={(e) => setIdoitConfig({ ...idoitConfig, idoit_auto_sync_enabled: e.target.checked })}
                    />
                    {t('enable_idoit_auto_sync')}
                  </label>
                  <div className="max-w-md">
                    <label className="block text-sm text-text-subtle mb-1">{t('idoit_sync_scope')}</label>
                    <select
                      className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text-base"
                      value={idoitConfig.idoit_sync_scope || 'all'}
                      onChange={(e) => setIdoitConfig({ ...idoitConfig, idoit_sync_scope: e.target.value === 'manual' ? 'manual' : 'all' })}
                    >
                      <option value="all">{t('idoit_sync_scope_all')}</option>
                      <option value="manual">{t('idoit_sync_scope_manual')}</option>
                    </select>
                    <p className="mt-1 text-xs text-text-subtle">{t('idoit_sync_scope_hint')}</p>
                  </div>
                  <div className="max-w-md">
                    <label className="block text-sm text-text-subtle mb-1">{t('idoit_create_policy')}</label>
                    <select
                      className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text-base"
                      value={idoitConfig.idoit_create_policy || 'match_only'}
                      onChange={(e) => setIdoitConfig({ ...idoitConfig, idoit_create_policy: e.target.value === 'create_missing' ? 'create_missing' : 'match_only' })}
                    >
                      <option value="match_only">{t('idoit_create_policy_match_only')}</option>
                      <option value="create_missing">{t('idoit_create_policy_create_missing')}</option>
                    </select>
                    <p className="mt-1 text-xs text-text-subtle">{t('idoit_create_policy_hint')}</p>
                  </div>
                  <div className="max-w-xs">
                    <label className="block text-sm text-text-subtle mb-1">{t('idoit_sync_interval_minutes')}</label>
                    <Input
                      type="number"
                      min={5}
                      max={1440}
                      value={String(idoitConfig.idoit_sync_interval_minutes || 60)}
                      onChange={(e) => setIdoitConfig({ ...idoitConfig, idoit_sync_interval_minutes: Math.min(1440, Math.max(5, Number(e.target.value) || 60)) })}
                    />
                    <p className="mt-1 text-xs text-text-subtle">{t('idoit_sync_interval_hint')}</p>
                    {idoitConfig.scheduler?.next_run_at && (
                      <p className="mt-1 text-xs text-text-subtle">{t('idoit_next_sync')}: {formatDateTime(idoitConfig.scheduler.next_run_at)}</p>
                    )}
                  </div>
                  <div className="max-w-xs">
                    <label className="block text-sm text-text-subtle mb-1">{t('idoit_offline_retire_days')}</label>
                    <Input
                      type="number"
                      min={1}
                      max={3650}
                      value={String(idoitConfig.idoit_offline_retire_days || 7)}
                      onChange={(e) => setIdoitConfig({ ...idoitConfig, idoit_offline_retire_days: Math.min(3650, Math.max(1, Number(e.target.value) || 7)) })}
                    />
                    <p className="mt-1 text-xs text-text-subtle">{t('idoit_offline_retire_days_hint')}</p>
                  </div>
                </div>

                <div className="mt-4 rounded-xl border border-border bg-surface2/30 p-4">
                  <div className="flex flex-col gap-1 mb-4">
                    <h3 className="text-sm font-semibold text-text-muted">{t('idoit_mapping_editor')}</h3>
                    <p className="text-xs text-text-subtle">{t('idoit_mapping_editor_hint')}</p>
                  </div>

                  {idoitMappingState.error ? (
                    <div className="rounded-lg border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
                      {t('idoit_mapping_json_invalid')}: {idoitMappingState.error}
                    </div>
                  ) : (
                    <div className="space-y-4">
                      <div className="grid md:grid-cols-2 gap-3">
                        <div>
                          <label className="block text-sm text-text-subtle mb-1">{t('idoit_mapping_name')}</label>
                          <Input
                            value={idoitMappingState.mapping?.name || ''}
                            onChange={(e) => updateIdoitMapping((mapping) => ({ ...mapping, name: e.target.value }))}
                            placeholder="Default i-doit mapping"
                          />
                        </div>
                        <div>
                          <label className="block text-sm text-text-subtle mb-1">{t('idoit_mapping_object_type')}</label>
                          <Input
                            value={idoitMappingState.mapping?.objectType || ''}
                            onChange={(e) => updateIdoitMapping((mapping) => ({ ...mapping, objectType: e.target.value.trim() }))}
                            placeholder="C__OBJTYPE__CLIENT"
                          />
                        </div>
                        <div>
                          <label className="block text-sm text-text-subtle mb-1">{t('idoit_external_id_field')}</label>
                          <Input
                            value={typeof idoitMappingState.mapping?.identity?.externalIdField === 'string' ? idoitMappingState.mapping.identity.externalIdField : ''}
                            onChange={(e) => updateIdoitIdentityField('externalIdField', e.target.value)}
                            placeholder=""
                          />
                        </div>
                        <div>
                          <label className="block text-sm text-text-subtle mb-1">{t('idoit_sync_status_field')}</label>
                          <Input
                            value={typeof idoitMappingState.mapping?.identity?.syncStatusField === 'string' ? idoitMappingState.mapping.identity.syncStatusField : idoitConfig.idoit_sync_status_field}
                            onChange={(e) => {
                              const value = e.target.value
                              setIdoitConfig((currentConfig) => {
                                if (!currentConfig) return currentConfig
                                const parsed = parseIdoitMapping(currentConfig.idoit_mapping_raw || '{}')
                                if (!parsed.mapping) return { ...currentConfig, idoit_sync_status_field: value }
                                return {
                                  ...currentConfig,
                                  idoit_sync_status_field: value,
                                  idoit_mapping_raw: stringifyIdoitMapping({
                                    ...parsed.mapping,
                                    identity: { ...(parsed.mapping.identity || {}), syncStatusField: value.trim() },
                                  }),
                                }
                              })
                            }}
                            placeholder=""
                          />
                        </div>
                      </div>

                      <div className="overflow-x-auto rounded-lg border border-border">
                        <table className="w-full text-sm">
                          <thead className="bg-surface2 text-text-subtle">
                            <tr>
                              <th className="text-left font-medium px-3 py-2">{t('idoit_lanlens_field')}</th>
                              <th className="text-left font-medium px-3 py-2">{t('idoit_target_field')}</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-border">
                            {IDOIT_MAPPING_FIELDS.map((field) => (
                              <tr key={field.key}>
                                <td className="px-3 py-2 text-text-muted whitespace-nowrap">{t(field.labelKey)}</td>
                                <td className="px-3 py-2 min-w-80">
                                  <Input
                                    value={idoitMappingState.mapping?.fields?.[field.key] || ''}
                                    onChange={(e) => updateIdoitFieldMapping(field.key, e.target.value)}
                                    placeholder={field.placeholder}
                                  />
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </div>

                <details className="mt-4">
                  <summary className="cursor-pointer text-sm text-text-subtle hover:text-text-base">{t('idoit_advanced_json')}</summary>
                  <textarea
                    className="mt-2 w-full min-h-72 rounded-lg border border-border bg-surface px-3 py-2 font-mono text-sm text-text-base focus:outline-none focus:ring-2 focus:ring-primary/40"
                    value={idoitConfig.idoit_mapping_raw || ''}
                    onChange={(e) => setIdoitConfig({ ...idoitConfig, idoit_mapping_raw: e.target.value })}
                    spellCheck={false}
                  />
                </details>

                {idoitConfig.mapping_errors?.length > 0 && (
                  <div className="mt-4 rounded-lg border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
                    <p className="font-medium mb-1">{t('idoit_mapping_validation')}</p>
                    <ul className="list-disc pl-5 space-y-1">
                      {idoitConfig.mapping_errors.map((error) => <li key={error}>{error}</li>)}
                    </ul>
                  </div>
                )}

                {idoitTestError && (
                  <div className="mt-4 rounded-lg border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
                    <p className="font-semibold mb-2">{t('idoit_connection_failed')}</p>
                    <div className="space-y-1">
                      <p>{idoitTestError.message}</p>
                      {idoitTestError.stage && <p><span className="font-medium">Stage:</span> {idoitTestError.stage}</p>}
                      {idoitTestError.status_code && <p><span className="font-medium">HTTP:</span> {idoitTestError.status_code}</p>}
                      {idoitTestError.endpoint && <p className="break-all"><span className="font-medium">Endpoint:</span> {idoitTestError.endpoint}</p>}
                      {idoitTestError.response_body && (
                        <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap rounded bg-background p-2 text-xs text-text-muted border border-border">{idoitTestError.response_body}</pre>
                      )}
                      {idoitTestError.jsonrpc_error != null && (
                        <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap rounded bg-background p-2 text-xs text-text-muted border border-border">{JSON.stringify(idoitTestError.jsonrpc_error, null, 2)}</pre>
                      )}
                    </div>
                  </div>
                )}

                <div className="mt-4 flex flex-wrap gap-3">
                  <Button onClick={saveIdoit} loading={saving}>{t('save_changes')}</Button>
                  <Button onClick={testIdoitConnection} loading={idoitTesting} variant="outline">{t('test_connection')}</Button>
                  <Button onClick={testIdoitMapping} loading={idoitTesting} variant="outline">{t('test_mapping')}</Button>
                  <Button onClick={enableIdoitSyncForAllDevices} loading={idoitEnablingAll} variant="outline">
                    {t('idoit_enable_sync_all')}
                  </Button>
                  <Button onClick={syncAllIdoitDevices} loading={idoitSyncingAll} variant="outline">
                    {idoitSyncProgress
                      ? t('idoit_sync_progress', { current: String(idoitSyncProgress.current), total: String(idoitSyncProgress.total) })
                      : t('idoit_sync_all_now')}
                  </Button>
                </div>
                {idoitSyncProgress && (
                  <div className="mt-3 rounded-lg border border-primary/30 bg-primary-dim/30 p-3 text-sm text-text-muted">
                    <div className="flex items-center justify-between gap-3 mb-2">
                      <span className="font-medium text-text-base">
                        {t('idoit_sync_progress', { current: String(idoitSyncProgress.current), total: String(idoitSyncProgress.total) })}
                      </span>
                      <span className="text-xs text-text-subtle">
                        {t('idoit_sync_progress_counts', {
                          success: String(idoitSyncProgress.success),
                          failure: String(idoitSyncProgress.failure),
                          skipped: String(idoitSyncProgress.skipped),
                        })}
                      </span>
                    </div>
                    <div className="h-2 rounded-full bg-surface overflow-hidden">
                      <div
                        className="h-full bg-primary transition-all"
                        style={{ width: `${Math.round((idoitSyncProgress.current / Math.max(idoitSyncProgress.total, 1)) * 100)}%` }}
                      />
                    </div>
                    {idoitSyncProgress.label && <p className="mt-2 text-xs text-text-subtle truncate">{idoitSyncProgress.label}</p>}
                  </div>
                )}

                <IdoitExportReviewPanel />

                <div className="mt-4 rounded-xl border border-border bg-surface2/30 p-4">
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <div>
                      <h3 className="text-sm font-semibold text-text-muted">{t('idoit_sync_logs')}</h3>
                      <p className="text-xs text-text-subtle">{t('idoit_sync_logs_hint')}</p>
                    </div>
                    <Button size="sm" variant="outline" onClick={loadIdoitLogs} loading={idoitLogsLoading}>{t('refresh')}</Button>
                  </div>
                  {idoitLogs.length === 0 ? (
                    <p className="text-sm text-text-subtle">{t('idoit_sync_logs_empty')}</p>
                  ) : (
                    <div className="max-h-96 overflow-auto rounded-lg border border-border bg-background">
                      <table className="min-w-full text-left text-xs">
                        <thead className="sticky top-0 bg-surface text-text-subtle">
                          <tr>
                            <th className="px-3 py-2 font-medium">{t('time')}</th>
                            <th className="px-3 py-2 font-medium">{t('result')}</th>
                            <th className="px-3 py-2 font-medium">{t('mode')}</th>
                            <th className="px-3 py-2 font-medium">{t('col_device')}</th>
                            <th className="px-3 py-2 font-medium">{t('message')}</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-border">
                          {idoitLogs.map((entry) => (
                            <tr key={entry.id} className="align-top">
                              <td className="whitespace-nowrap px-3 py-2 text-text-subtle">{formatDateTime(entry.created_at)}</td>
                              <td className="px-3 py-2">
                                <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${entry.result === 'failure' ? 'bg-danger/15 text-danger' : entry.result === 'skipped' ? 'bg-warning/15 text-warning' : 'bg-success/15 text-success'}`}>
                                  {entry.result}
                                </span>
                              </td>
                              <td className="px-3 py-2 text-text-subtle">{entry.mode}</td>
                              <td className="px-3 py-2">
                                {entry.device_id ? (
                                  <Link
                                    to={`/devices/${entry.device_id}`}
                                    className="font-medium text-primary hover:underline"
                                    title={`Device #${entry.device_id}`}
                                  >
                                    {entry.device_name || `Device #${entry.device_id}`}
                                  </Link>
                                ) : (
                                  <span className="text-text-subtle">{entry.device_name || '—'}</span>
                                )}
                              </td>
                              <td className="px-3 py-2 text-text-muted">
                                <p>{entry.message || '—'}</p>
                                {Boolean(entry.details?.warnings) && (
                                  <pre className="mt-1 max-w-xl whitespace-pre-wrap break-words rounded bg-warning/10 p-2 text-[11px] text-warning">{JSON.stringify(entry.details?.warnings, null, 2)}</pre>
                                )}
                                {Boolean(entry.details?.error) && (
                                  <pre className="mt-1 max-w-xl whitespace-pre-wrap break-words rounded bg-danger/10 p-2 text-[11px] text-danger">{JSON.stringify(entry.details?.error, null, 2)}</pre>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </>
            )}
          </Card>
        </div>
      </div>
      )}

    </div>
  )
}
