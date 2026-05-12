import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import Input from '../components/ui/Input'
import Spinner from '../components/ui/Spinner'
import { settingsApi, type AllSettings } from '../api/settings'
import { idoitApi, type IdoitConfig } from '../api/idoit'
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

export default function Settings() {
  const { t, lang, setLang } = useI18n()
  const [settings, setSettings] = useState<AllSettings | null>(null)
  const [saving, setSaving] = useState(false)
  const [checkingUpdate, setCheckingUpdate] = useState(false)
  const [telegramTokenDirty, setTelegramTokenDirty] = useState(false)
  const [idoitConfig, setIdoitConfig] = useState<IdoitConfig | null>(null)
  const [idoitLoadError, setIdoitLoadError] = useState(false)
  const [idoitApiKey, setIdoitApiKey] = useState('')
  const [idoitBasicPassword, setIdoitBasicPassword] = useState('')
  const [idoitTesting, setIdoitTesting] = useState(false)
  const [idoitTestError, setIdoitTestError] = useState<IdoitErrorDetails | null>(null)
  const [activeSection, setActiveSection] = useState<'system' | 'database' | 'network' | 'notifications' | 'inventory' | 'backup' | 'cmdb'>('system')
  const setShowServicesNav = useUiSettingsStore((state) => state.setShowServicesNav)
  const setShowDhcpMonitorNav = useUiSettingsStore((state) => state.setShowDhcpMonitorNav)

  useEffect(() => {
    // Load settings once on mount. Language switches should only re-render labels,
    // not re-fetch and overwrite form fields or the mapping editor mid-edit.
    settingsApi.get().then((data) => {
      setSettings(data)
      setShowServicesNav(data.show_services_nav)
      setShowDhcpMonitorNav(data.show_dhcp_monitor_nav)
      setTelegramTokenDirty(false)
    }).catch(() => {
      toast.error(t('settings_load_failed'))
    })
    loadIdoitConfig()
  }, [])

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
    } catch {
      setIdoitConfig(null)
      setIdoitLoadError(true)
      toast.error(t('idoit_settings_load_failed'))
    }
  }

  async function saveTelegram() {
    setSaving(true)
    try {
      await settingsApi.updateTelegram({
        telegram_bot_token: current.telegram_bot_token,
        telegram_chat_id: current.telegram_chat_id,
        telegram_enabled: current.telegram_enabled,
        notify_telegram_update: current.notify_telegram_update,
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
        setShowServicesNav(data.show_services_nav)
        setShowDhcpMonitorNav(data.show_dhcp_monitor_nav)
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
        idoit_sync_interval_minutes: idoitConfig.idoit_sync_interval_minutes,
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
        idoit_sync_interval_minutes: idoitConfig.idoit_sync_interval_minutes,
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

  async function saveUi() {
    setSaving(true)
    try {
      await settingsApi.updateUi(current.show_services_nav, current.show_dhcp_monitor_nav)
      setShowServicesNav(current.show_services_nav)
      setShowDhcpMonitorNav(current.show_dhcp_monitor_nav)
      toast.success(t('ui_settings_saved'))
    } catch {
      toast.error(t('ui_settings_save_failed'))
    } finally {
      setSaving(false)
    }
  }

  const settingSections = [
    { key: 'system' as const, label: t('system') },
    { key: 'database' as const, label: t('database') },
    { key: 'network' as const, label: t('network_discovery') },
    { key: 'notifications' as const, label: t('notifications') },
    { key: 'inventory' as const, label: t('inventory_tools_title') },
    { key: 'backup' as const, label: t('backup_restore') },
    { key: 'cmdb' as const, label: t('cmdb_tab') },
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
            <h2 className="text-lg font-semibold text-text-base mb-1">{t('ui_settings')}</h2>
            <p className="text-sm text-text-subtle mb-4">{t('ui_settings_description')}</p>
            <div className="space-y-2">
              <label className="flex items-center gap-2 text-sm text-text-base">
                <input
                  type="checkbox"
                  checked={current.show_services_nav}
                  onChange={(e) => setSettings({ ...current, show_services_nav: e.target.checked })}
                />
                {t('show_services_nav')}
              </label>
              <label className="flex items-center gap-2 text-sm text-text-base">
                <input
                  type="checkbox"
                  checked={current.show_dhcp_monitor_nav}
                  onChange={(e) => setSettings({ ...current, show_dhcp_monitor_nav: e.target.checked })}
                />
                {t('show_dhcp_monitor_nav')}
              </label>
            </div>
            <div className="mt-4">
              <Button onClick={saveUi} loading={saving}>{t('save_changes')}</Button>
            </div>
          </Card>

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
                      placeholder="C__OBJTYPE__SERVER"
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-text-subtle mb-1">{t('idoit_sync_status_field')}</label>
                    <Input
                      value={idoitConfig.idoit_sync_status_field}
                      onChange={(e) => setIdoitConfig({ ...idoitConfig, idoit_sync_status_field: e.target.value })}
                      placeholder="C__CATG__GLOBAL.comment"
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
                </div>

                <div className="mt-4">
                  <label className="block text-sm text-text-subtle mb-1">{t('idoit_mapping_json')}</label>
                  <textarea
                    className="w-full min-h-72 rounded-lg border border-border bg-surface px-3 py-2 font-mono text-sm text-text-base focus:outline-none focus:ring-2 focus:ring-primary/40"
                    value={idoitConfig.idoit_mapping_raw || ''}
                    onChange={(e) => setIdoitConfig({ ...idoitConfig, idoit_mapping_raw: e.target.value })}
                    spellCheck={false}
                  />
                </div>

                {/* The mapping editor intentionally stays plain text so invalid JSON
                    can be fixed in-place instead of being hidden by a parser. */}
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
