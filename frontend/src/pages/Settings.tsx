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
      toast.error(lang === 'de' ? 'Einstellungen konnten nicht geladen werden' : 'Failed to load settings')
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
      toast.success(lang === 'de' ? 'Telegram-Einstellungen gespeichert' : 'Telegram settings saved')
    } catch {
      toast.error(lang === 'de' ? 'Telegram-Einstellungen konnten nicht gespeichert werden' : 'Failed to save Telegram settings')
    } finally {
      setSaving(false)
    }
  }

  async function saveDhcp() {
    setSaving(true)
    try {
      await settingsApi.updateDhcp(current.dhcp_start, current.dhcp_end)
      toast.success(lang === 'de' ? 'DHCP-Bereich gespeichert' : 'DHCP range saved')
    } catch {
      toast.error(lang === 'de' ? 'DHCP-Bereich konnte nicht gespeichert werden' : 'Failed to save DHCP range')
    } finally {
      setSaving(false)
    }
  }

  async function saveScanRange() {
    setSaving(true)
    try {
      await settingsApi.updateScanRange(current.scan_start, current.scan_end)
      toast.success(lang === 'de' ? 'Scan-Bereich gespeichert' : 'Scan range saved')
    } catch {
      toast.error(lang === 'de' ? 'Scan-Bereich konnte nicht gespeichert werden' : 'Failed to save scan range')
    } finally {
      setSaving(false)
    }
  }

  async function saveSchedule() {
    setSaving(true)
    try {
      await settingsApi.updateScanSchedule(current.scan_interval_minutes)
      toast.success(lang === 'de' ? 'Scan-Intervall gespeichert' : 'Scan interval saved')
    } catch {
      toast.error(lang === 'de' ? 'Scan-Intervall konnte nicht gespeichert werden' : 'Failed to save scan interval')
    } finally {
      setSaving(false)
    }
  }

  async function savePortScanSettings() {
    setSaving(true)
    try {
      await settingsApi.updatePortScanSettings(current.port_scan_range)
      toast.success(lang === 'de' ? 'Port-Scan-Einstellungen gespeichert' : 'Port scan settings saved')
    } catch {
      toast.error(lang === 'de' ? 'Port-Scan-Einstellungen konnten nicht gespeichert werden' : 'Failed to save port scan settings')
    } finally {
      setSaving(false)
    }
  }

  async function saveServerUrl() {
    setSaving(true)
    try {
      await settingsApi.updateServerUrl(current.server_url)
      toast.success(lang === 'de' ? 'Server-URL gespeichert' : 'Server URL saved')
    } catch {
      toast.error(lang === 'de' ? 'Server-URL konnte nicht gespeichert werden' : 'Failed to save server URL')
    } finally {
      setSaving(false)
    }
  }

  async function testTelegram() {
    try {
      await settingsApi.testTelegram()
      toast.success(lang === 'de' ? 'Testnachricht gesendet' : 'Test message sent')
    } catch {
      toast.error(lang === 'de' ? 'Telegram-Test fehlgeschlagen' : 'Telegram test failed')
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
      toast.success(lang === 'de' ? 'E-Mail-Einstellungen gespeichert' : 'Email settings saved')
    } catch {
      toast.error(lang === 'de' ? 'Speichern fehlgeschlagen' : 'Failed to save email settings')
    } finally {
      setSaving(false)
    }
  }

  async function testSmtp() {
    try {
      await settingsApi.testSmtp()
      toast.success(lang === 'de' ? 'Test-E-Mail gesendet' : 'Test email sent')
    } catch {
      toast.error(lang === 'de' ? 'SMTP-Test fehlgeschlagen' : 'SMTP test failed')
    }
  }

  async function checkForUpdates() {
    setCheckingUpdate(true)
    try {
      const result = await settingsApi.checkUpdate()
      if (result.update_available) {
        toast.success(
          lang === 'de'
            ? `Update verfügbar: v${result.latest_version}`
            : `Update available: v${result.latest_version}`
        )
      } else {
        toast.success(
          lang === 'de'
            ? `Kein neueres Update verfügbar (aktuell: v${result.current_version})`
            : `No newer update available (current: v${result.current_version})`
        )
      }
    } catch {
      toast.error(lang === 'de' ? 'Update-Prüfung fehlgeschlagen' : 'Update check failed')
    } finally {
      setCheckingUpdate(false)
    }
  }

  async function handleExportSettings() {
    try {
      const resp = await adminApi.exportSettings()
      downloadBlob(resp.data, 'lanlens-settings.json')
    } catch {
      toast.error(lang === 'de' ? 'Export fehlgeschlagen' : 'Export failed')
    }
  }

  async function handleExportDatabase() {
    try {
      const resp = await adminApi.exportDatabase()
      downloadBlob(resp.data, 'lanlens-backup.db')
    } catch {
      toast.error(lang === 'de' ? 'Datenbankexport fehlgeschlagen' : 'Database export failed')
    }
  }

  async function handleImportSettings(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const result = await adminApi.importSettings(file)
      toast.success(result.data.message || 'Settings imported')
      settingsApi.get().then(setSettings)
    } catch {
      toast.error(lang === 'de' ? 'Import fehlgeschlagen' : 'Import failed')
    }
    e.target.value = '' // reset file input
  }

  async function saveCmdb() {
    setSaving(true)
    try {
      await settingsApi.updateCmdb(current.cmdb_id_prefix, current.cmdb_id_digits)
      toast.success(lang === 'de' ? 'CMDB-Einstellungen gespeichert' : 'CMDB settings saved')
    } catch {
      toast.error(lang === 'de' ? 'Speichern fehlgeschlagen' : 'Failed to save CMDB settings')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-8">
      {/* ── SYSTEM ────────────────────────────────────────────────────────── */}
      <div>
        <h2 className="text-xs font-semibold text-text-subtle uppercase tracking-widest mb-3">
          {lang === 'de' ? 'System' : 'System'}
        </h2>
        <div className="space-y-4">
          <Card>
            <div className="flex items-center justify-between gap-4 mb-4">
              <div>
                <h2 className="text-lg font-semibold text-text-base">LanLens</h2>
                <p className="text-sm text-text-subtle">
                  {lang === 'de' ? 'Allgemeine Instanz- und Update-Einstellungen' : 'General instance and update settings'}
                </p>
              </div>
              <Button onClick={checkForUpdates} loading={checkingUpdate}>
                {lang === 'de' ? 'Jetzt auf Updates prüfen' : 'Check for updates now'}
              </Button>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label className="block text-sm text-text-subtle mb-1">
                  {lang === 'de' ? 'Sprache' : lang === 'it' ? 'Lingua' : 'Language'}
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
              {lang === 'de' ? 'Export & Import' : 'Export & Import'}
            </h2>
            <p className="text-sm text-text-subtle mb-4">
              {lang === 'de'
                ? 'Einstellungen und Datenbank sichern oder auf ein neues System übertragen.'
                : 'Back up settings and database or migrate to a new system.'}
            </p>
            <div className="flex flex-wrap gap-3">
              <Button variant="outline" onClick={handleExportSettings}>
                {lang === 'de' ? '⬇ Einstellungen exportieren' : '⬇ Export Settings'}
              </Button>
              <Button variant="outline" onClick={handleExportDatabase}>
                {lang === 'de' ? '⬇ Datenbank exportieren (.db)' : '⬇ Export Database (.db)'}
              </Button>
            </div>
            <div className="mt-4 pt-4 border-t border-border space-y-3">
              <p className="text-xs text-text-subtle font-medium uppercase tracking-wide">
                {lang === 'de' ? 'Importieren' : 'Import'}
              </p>
              <label className="flex items-center gap-3 cursor-pointer group">
                <span className="px-3 py-1.5 text-xs font-medium rounded-lg border border-border bg-surface2 text-text-muted group-hover:text-primary group-hover:border-primary/50 transition-colors">
                  {lang === 'de' ? '⬆ Einstellungen importieren (.json)' : '⬆ Import Settings (.json)'}
                </span>
                <input
                  type="file"
                  accept=".json"
                  className="hidden"
                  onChange={handleImportSettings}
                />
              </label>
              <p className="text-xs text-text-subtle">
                {lang === 'de'
                  ? 'Für den Datenbankimport: Lege die .db Datei als DB_PATH im Container ab und starte neu.'
                  : 'For database import: place the .db file at DB_PATH in the container and restart.'}
              </p>
            </div>
          </Card>

          <Card>
            <h2 className="text-lg font-semibold text-text-base mb-1">CMDB IDs</h2>
            <p className="text-sm text-text-subtle mb-4">
              {lang === 'de'
                ? 'Automatische eindeutige ID für jedes registrierte Gerät. Format: PREFIX-NNNN'
                : 'Automatic unique ID for every registered device. Format: PREFIX-NNNN'}
            </p>
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label className="block text-sm text-text-subtle mb-1">
                  {lang === 'de' ? 'Präfix' : 'Prefix'}
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
                  {lang === 'de' ? 'Stellen (Ziffern)' : 'Digits'}
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
              {lang === 'de' ? 'Vorschau:' : 'Preview:'}{' '}
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
          {lang === 'de' ? 'Datenbank' : 'Database'}
        </h2>
        <div className="space-y-4">
          <Card>
            <h2 className="text-lg font-semibold text-text-base mb-1">
              {lang === 'de' ? 'Datenbankverbindung' : 'Database Connection'}
            </h2>
            <p className="text-sm text-text-subtle mb-3">
              {lang === 'de'
                ? 'Standardmäßig verwendet LanLens SQLite. Für produktive Umgebungen kann MariaDB/MySQL über die Umgebungsvariable DATABASE_URL konfiguriert werden.'
                : 'LanLens uses SQLite by default. For production environments, MariaDB/MySQL can be configured via the DATABASE_URL environment variable.'}
            </p>
            <div className="bg-surface2 rounded-lg border border-border p-3 space-y-2 text-xs font-mono">
              <p className="text-text-subtle"># docker-compose.yml environment:</p>
              <p className="text-success">DATABASE_URL=mysql+pymysql://user:pass@mariadb:3306/lanlens</p>
            </div>
            <p className="text-xs text-text-subtle mt-3">
              {lang === 'de'
                ? 'Zusätzlich benötigtes Python-Paket: PyMySQL. Siehe Dokumentation für die vollständige MariaDB-Anleitung.'
                : 'Additional Python package required: PyMySQL. See documentation for the full MariaDB setup guide.'}
            </p>
          </Card>
        </div>
      </div>

      {/* ── NETWORK DISCOVERY ─────────────────────────────────────────────── */}
      <div>
        <h2 className="text-xs font-semibold text-text-subtle uppercase tracking-widest mb-3">
          {lang === 'de' ? 'Netzwerk-Erkennung' : 'Network Discovery'}
        </h2>
        <div className="space-y-4">
          <Card>
            <h2 className="text-lg font-semibold text-text-base mb-2">{lang === 'de' ? 'DHCP-Bereich' : 'DHCP range'}</h2>
            <p className="text-sm text-text-subtle mb-4">
              {lang === 'de'
                ? 'Dieser Bereich wird nur für DHCP-Markierung und Einordnung der Geräte genutzt.'
                : 'This range is only used for DHCP tagging and device classification.'}
            </p>
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label className="block text-sm text-text-subtle mb-1">{lang === 'de' ? 'DHCP-Start' : 'DHCP start'}</label>
                <Input value={current.dhcp_start} onChange={(e) => setSettings({ ...current, dhcp_start: e.target.value })} />
              </div>
              <div>
                <label className="block text-sm text-text-subtle mb-1">{lang === 'de' ? 'DHCP-Ende' : 'DHCP end'}</label>
                <Input value={current.dhcp_end} onChange={(e) => setSettings({ ...current, dhcp_end: e.target.value })} />
              </div>
            </div>
            <div className="mt-4">
              <Button onClick={saveDhcp} loading={saving}>{t('save_changes')}</Button>
            </div>
          </Card>

          <Card>
            <h2 className="text-lg font-semibold text-text-base mb-2">{lang === 'de' ? 'Scan-Bereich' : 'Scan range'}</h2>
            <p className="text-sm text-text-subtle mb-4">
              {lang === 'de'
                ? 'Dieser IPv4-Bereich wird aktiv per ARP gescannt. Das funktioniert direkt nur im lokal erreichbaren Layer-2-Netz.'
                : 'This IPv4 range is actively scanned via ARP. This works directly only on the locally reachable Layer 2 network.'}
            </p>
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label className="block text-sm text-text-subtle mb-1">{lang === 'de' ? 'Scan-Start' : 'Scan start'}</label>
                <Input value={current.scan_start} onChange={(e) => setSettings({ ...current, scan_start: e.target.value })} />
              </div>
              <div>
                <label className="block text-sm text-text-subtle mb-1">{lang === 'de' ? 'Scan-Ende' : 'Scan end'}</label>
                <Input value={current.scan_end} onChange={(e) => setSettings({ ...current, scan_end: e.target.value })} />
              </div>
            </div>
            <div className="mt-4">
              <Button onClick={saveScanRange} loading={saving}>{t('save_changes')}</Button>
            </div>
          </Card>

          <Card>
            <h2 className="text-lg font-semibold text-text-base mb-4">{lang === 'de' ? 'Scan-Zeitplan' : 'Scan schedule'}</h2>
            <div>
              <label className="block text-sm text-text-subtle mb-1">{lang === 'de' ? 'Intervall in Minuten' : 'Interval in minutes'}</label>
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
            <h2 className="text-lg font-semibold text-text-base mb-2">{lang === 'de' ? 'Port-Scan-Bereich' : 'Port scan range'}</h2>
            <p className="text-sm text-text-subtle mb-4">
              {lang === 'de'
                ? 'Legt fest, welche Ports bei einem Gerätescan geprüft werden. Beispiele: top:1000 · 1-65535 · 22,80,443 · 1-1024,8080,8443'
                : 'Defines which ports are checked when scanning a device. Examples: top:1000 · 1-65535 · 22,80,443 · 1-1024,8080,8443'}
            </p>
            <div>
              <label className="block text-sm text-text-subtle mb-1">
                {lang === 'de' ? 'Port-Bereich / Liste' : 'Port range / list'}
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
          {lang === 'de' ? 'Benachrichtigungen' : 'Notifications'}
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
                {lang === 'de' ? 'Telegram-Benachrichtigungen aktivieren' : 'Enable Telegram notifications'}
              </label>
              <label className="flex items-center gap-2 text-sm text-text-base">
                <input
                  type="checkbox"
                  checked={current.notify_telegram_update}
                  onChange={(e) => setSettings({ ...current, notify_telegram_update: e.target.checked })}
                />
                {lang === 'de' ? 'Update-Benachrichtigungen senden' : 'Send update notifications'}
              </label>
            </div>
            <div className="mt-4 flex gap-3">
              <Button onClick={saveTelegram} loading={saving}>{t('save_changes')}</Button>
              <Button onClick={testTelegram} variant="outline">{lang === 'de' ? 'Telegram testen' : 'Test Telegram'}</Button>
            </div>
          </Card>

          <Card>
            <h2 className="text-lg font-semibold text-text-base mb-4">
              {lang === 'de' ? 'E-Mail (SMTP)' : 'Email (SMTP)'}
            </h2>
            <div className="grid gap-4">
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <label className="block text-sm text-text-subtle mb-1">
                    {lang === 'de' ? 'SMTP-Server' : 'SMTP Host'}
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
                    {lang === 'de' ? 'Benutzername' : 'Username'}
                  </label>
                  <Input
                    value={current.smtp_username}
                    onChange={(e) => setSettings({ ...current, smtp_username: e.target.value })}
                    placeholder="user@example.com"
                  />
                </div>
                <div>
                  <label className="block text-sm text-text-subtle mb-1">
                    {lang === 'de' ? 'Passwort' : 'Password'}
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
                    {lang === 'de' ? 'Absender-E-Mail' : 'From Email'}
                  </label>
                  <Input
                    value={current.smtp_from_email}
                    onChange={(e) => setSettings({ ...current, smtp_from_email: e.target.value })}
                    placeholder="lanlens@example.com"
                  />
                </div>
                <div>
                  <label className="block text-sm text-text-subtle mb-1">
                    {lang === 'de' ? 'Empfänger-E-Mail' : 'To Email'}
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
                {lang === 'de' ? 'E-Mail-Benachrichtigungen aktivieren' : 'Enable email notifications'}
              </label>
              <label className="flex items-center gap-2 text-sm text-text-base">
                <input
                  type="checkbox"
                  checked={current.smtp_use_tls}
                  onChange={(e) => setSettings({ ...current, smtp_use_tls: e.target.checked })}
                />
                {lang === 'de' ? 'STARTTLS verwenden' : 'Use STARTTLS'}
              </label>
            </div>
            <div className="mt-4 flex gap-3">
              <Button onClick={saveSmtp} loading={saving}>{t('save_changes')}</Button>
              <Button onClick={testSmtp} variant="outline">
                {lang === 'de' ? 'E-Mail testen' : 'Test Email'}
              </Button>
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
