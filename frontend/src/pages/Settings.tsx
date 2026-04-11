import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import Input from '../components/ui/Input'
import Spinner from '../components/ui/Spinner'
import CredentialManager from '../components/settings/CredentialManager'
import { settingsApi, type AllSettings } from '../api/settings'
import { useI18n } from '../i18n'

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

  return (
    <div className="space-y-6">
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
            <label className="block text-sm text-text-subtle mb-1">{lang === 'de' ? 'Sprache' : 'Language'}</label>
            <select
              className="input-field"
              value={lang}
              onChange={(e) => setLang(e.target.value as 'de' | 'en')}
            >
              <option value="en">English</option>
              <option value="de">Deutsch</option>
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
        <h2 className="text-sm font-semibold text-text-muted mb-1">{t('deep_scan_credentials')}</h2>
        <p className="text-xs text-text-subtle mb-4">
          {lang === 'de'
            ? 'SSH- und WinRM-Zugangsdaten für den Tiefenscan. Passwörter werden verschlüsselt gespeichert.'
            : 'SSH and WinRM credentials for deep scan. Passwords are stored encrypted.'}
        </p>
        <CredentialManager />
      </Card>
    </div>
  )
}
