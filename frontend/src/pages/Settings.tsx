import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import Input from '../components/ui/Input'
import Spinner from '../components/ui/Spinner'
import { settingsApi, type AllSettings } from '../api/settings'
import { adminApi } from '../api/admin'
import { useI18n } from '../i18n'

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

export default function Settings() {
  const { t, lang, setLang } = useI18n()
  const [settings, setSettings] = useState<AllSettings | null>(null)
  const [saving, setSaving] = useState(false)
  const [checkingUpdate, setCheckingUpdate] = useState(false)

  useEffect(() => {
    settingsApi.get().then(setSettings).catch(() => {
      toast.error(t('settings_load_failed'))
    })
  }, [lang])

  if (!settings) {
    return (
      <div className="flex justify-center py-16">
        <Spinner size="lg" />
      </div>
    )
  }

  const current = settings

  async function saveTelegram() {
    setSaving(true)
    try {
      await settingsApi.updateTelegram({
        telegram_bot_token: current.telegram_bot_token,
        telegram_chat_id: current.telegram_chat_id,
        telegram_enabled: current.telegram_enabled,
        notify_telegram_update: current.notify_telegram_update,
      })
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
      await settingsApi.updateScanRange(current.scan_start, current.scan_end)
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
      downloadBlob(resp.data, 'lanlens-backup.db')
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
      settingsApi.get().then(setSettings)
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

  return (
    <div className="space-y-8">
      {/* ── SYSTEM ────────────────────────────────────────────────────────── */}
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
                  onChange={(e) => setLang(e.target.value as 'en' | 'de' | 'it')}
                >
                  <option value="en">English</option>
                  <option value="de">Deutsch</option>
                  <option value="it">Italiano</option>
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
                {t('import_label')}
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
        </div>
      </div>

      {/* ── DATABASE ──────────────────────────────────────────────────────── */}
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

      {/* ── NETWORK DISCOVERY ─────────────────────────────────────────────── */}
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

      {/* ── NOTIFICATIONS ─────────────────────────────────────────────────── */}
      <div>
        <h2 className="text-xs font-semibold text-text-subtle uppercase tracking-widest mb-3">
          {t('notifications')}
        </h2>
        <div className="space-y-4">
          <Card>
            <h2 className="text-lg font-semibold text-text-base mb-4">Telegram</h2>
            <div className="grid gap-4">
              <div>
                <label className="block text-sm text-text-subtle mb-1">Bot Token</label>
                <Input
                  value={current.telegram_bot_token}
                  onChange={(e) => setSettings({ ...current, telegram_bot_token: e.target.value })}
                />
              </div>
              <div>
                <label className="block text-sm text-text-subtle mb-1">Chat ID</label>
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
        </div>
      </div>
    </div>
  )
}
