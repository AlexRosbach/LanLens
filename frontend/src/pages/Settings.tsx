import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { AllSettings, settingsApi } from '../api/settings'
import { authApi } from '../api/auth'
import { useAuthStore } from '../store/authStore'
import Button from '../components/ui/Button'
import Input from '../components/ui/Input'
import Card from '../components/ui/Card'
import Spinner from '../components/ui/Spinner'

type Tab = 'network' | 'notifications' | 'security'

function Toggle({ enabled, onToggle, label }: { enabled: boolean; onToggle: () => void; label: string }) {
  return (
    <label className="flex items-center gap-3 cursor-pointer">
      <div
        onClick={onToggle}
        className={`w-10 h-5 rounded-full transition-colors relative flex-shrink-0 ${enabled ? 'bg-primary' : 'bg-surface2 border border-border'}`}
      >
        <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${enabled ? 'translate-x-5' : 'translate-x-0.5'}`} />
      </div>
      <span className="text-sm text-text-muted">{label}</span>
    </label>
  )
}

export default function Settings() {
  const [tab, setTab] = useState<Tab>('network')
  const [settings, setSettings] = useState<AllSettings | null>(null)
  const [loading, setLoading] = useState(true)

  // Network
  const [dhcpStart, setDhcpStart] = useState('')
  const [dhcpEnd, setDhcpEnd] = useState('')
  const [interval, setInterval] = useState(5)

  // Server URL
  const [serverUrl, setServerUrl] = useState('')
  const [savingUrl, setSavingUrl] = useState(false)

  // Telegram
  const [botToken, setBotToken] = useState('')
  const [chatId, setChatId] = useState('')
  const [telegramEnabled, setTelegramEnabled] = useState(false)
  const [notifyTelegramUpdate, setNotifyTelegramUpdate] = useState(false)
  const [testing, setTesting] = useState(false)

  // Security
  const [currentPw, setCurrentPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [savingPw, setSavingPw] = useState(false)

  const [saving, setSaving] = useState(false)
  const { logout } = useAuthStore()

  useEffect(() => {
    settingsApi.get().then((s) => {
      setSettings(s)
      setDhcpStart(s.dhcp_start)
      setDhcpEnd(s.dhcp_end)
      setInterval(s.scan_interval_minutes)
      setBotToken(s.telegram_bot_token)
      setChatId(s.telegram_chat_id)
      setTelegramEnabled(s.telegram_enabled)
      setNotifyTelegramUpdate(s.notify_telegram_update)
      setServerUrl(s.server_url ?? '')
    }).finally(() => setLoading(false))
  }, [])

  async function saveDhcp() {
    setSaving(true)
    try {
      await settingsApi.updateDhcp(dhcpStart, dhcpEnd)
      toast.success('DHCP range saved')
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? 'Failed to save')
    } finally { setSaving(false) }
  }

  async function saveSchedule() {
    setSaving(true)
    try {
      await settingsApi.updateScanSchedule(interval)
      toast.success('Scan schedule saved')
    } catch { toast.error('Failed to save') } finally { setSaving(false) }
  }

  async function saveServerUrl() {
    setSavingUrl(true)
    try {
      await settingsApi.updateServerUrl(serverUrl)
      toast.success('Server URL saved')
    } catch { toast.error('Failed to save') } finally { setSavingUrl(false) }
  }

  async function saveTelegram() {
    setSaving(true)
    try {
      await settingsApi.updateTelegram({
        telegram_bot_token: botToken,
        telegram_chat_id: chatId,
        telegram_enabled: telegramEnabled,
        notify_telegram_update: notifyTelegramUpdate,
      })
      toast.success('Telegram settings saved')
    } catch { toast.error('Failed to save') } finally { setSaving(false) }
  }

  async function testTelegram() {
    setTesting(true)
    try {
      await settingsApi.testTelegram()
      toast.success('Test message sent!')
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? 'Test failed')
    } finally { setTesting(false) }
  }

  async function changePassword() {
    if (newPw !== confirmPw) { toast.error('Passwords do not match'); return }
    if (newPw.length < 8) { toast.error('Password must be at least 8 characters'); return }
    setSavingPw(true)
    try {
      await authApi.changePassword(currentPw, newPw)
      toast.success('Password changed')
      setCurrentPw(''); setNewPw(''); setConfirmPw('')
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? 'Failed to change password')
    } finally { setSavingPw(false) }
  }

  if (loading) return <div className="flex justify-center py-16"><Spinner size="lg" /></div>

  return (
    <div className="max-w-2xl mx-auto flex flex-col gap-5">
      <h1 className="text-xl font-bold text-text-base">Settings</h1>

      {/* Tabs */}
      <div className="flex gap-1 bg-surface border border-border rounded-lg p-1 w-fit">
        {(['network', 'notifications', 'security'] as Tab[]).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors capitalize
              ${tab === t ? 'bg-surface2 text-text-base' : 'text-text-subtle hover:text-text-muted'}`}>
            {t}
          </button>
        ))}
      </div>

      {tab === 'network' && (
        <>
          <Card>
            <h2 className="text-sm font-semibold text-text-muted mb-4">DHCP Scan Range</h2>
            <div className="grid grid-cols-2 gap-4 mb-4">
              <Input label="Start IP" value={dhcpStart} onChange={(e) => setDhcpStart(e.target.value)} placeholder="192.168.1.1" />
              <Input label="End IP" value={dhcpEnd} onChange={(e) => setDhcpEnd(e.target.value)} placeholder="192.168.1.254" />
            </div>
            <Button onClick={saveDhcp} loading={saving} size="sm">Save Range</Button>
          </Card>

          <Card>
            <h2 className="text-sm font-semibold text-text-muted mb-4">Scan Schedule</h2>
            <div className="flex items-end gap-4">
              <div className="flex-1">
                <Input
                  label="Interval (minutes)"
                  type="number"
                  min={1}
                  max={1440}
                  value={interval}
                  onChange={(e) => setInterval(Number(e.target.value))}
                  hint="How often to scan the network automatically"
                />
              </div>
              <Button onClick={saveSchedule} loading={saving} size="sm">Save</Button>
            </div>
          </Card>

          <Card>
            <h2 className="text-sm font-semibold text-text-muted mb-1">Server URL</h2>
            <p className="text-xs text-text-subtle mb-4">
              The public URL of this LanLens instance (e.g. behind a reverse proxy). Used to generate direct links in Telegram notifications.
            </p>
            <div className="flex items-end gap-4">
              <div className="flex-1">
                <Input
                  label="URL"
                  placeholder="https://lanlens.example.com"
                  value={serverUrl}
                  onChange={(e) => setServerUrl(e.target.value)}
                  hint="Leave empty to omit links from notifications"
                />
              </div>
              <Button onClick={saveServerUrl} loading={savingUrl} size="sm">Save</Button>
            </div>
          </Card>
        </>
      )}

      {tab === 'notifications' && (
        <Card>
          <h2 className="text-sm font-semibold text-text-muted mb-1">Telegram Notifications</h2>
          <p className="text-xs text-text-subtle mb-4">
            Get notified on Telegram when new devices are detected.
            Create a bot via <span className="text-primary">@BotFather</span> and find your Chat ID via <span className="text-primary">@userinfobot</span>.
          </p>

          <div className="flex flex-col gap-4">
            <Input
              label="Bot Token"
              type="password"
              placeholder="1234567890:ABCdef..."
              value={botToken}
              onChange={(e) => setBotToken(e.target.value)}
            />
            <Input
              label="Chat ID"
              placeholder="-1001234567890 or 123456789"
              value={chatId}
              onChange={(e) => setChatId(e.target.value)}
            />

            <div className="flex flex-col gap-3 pt-1">
              <Toggle
                enabled={telegramEnabled}
                onToggle={() => setTelegramEnabled(!telegramEnabled)}
                label="Enable Telegram notifications (new devices)"
              />
              <Toggle
                enabled={notifyTelegramUpdate}
                onToggle={() => setNotifyTelegramUpdate(!notifyTelegramUpdate)}
                label="Notify via Telegram when a new LanLens version is available"
              />
            </div>

            <div className="flex gap-3 pt-1">
              <Button onClick={saveTelegram} loading={saving} size="sm">Save Settings</Button>
              <Button variant="outline" onClick={testTelegram} loading={testing} size="sm">Send Test</Button>
            </div>
          </div>
        </Card>
      )}

      {tab === 'security' && (
        <Card>
          <h2 className="text-sm font-semibold text-text-muted mb-4">Change Password</h2>
          <div className="flex flex-col gap-4">
            <Input label="Current Password" type="password" value={currentPw} onChange={(e) => setCurrentPw(e.target.value)} />
            <Input label="New Password" type="password" placeholder="Minimum 8 characters" value={newPw} onChange={(e) => setNewPw(e.target.value)} />
            <Input label="Confirm New Password" type="password" value={confirmPw} onChange={(e) => setConfirmPw(e.target.value)}
              error={confirmPw && newPw !== confirmPw ? 'Passwords do not match' : undefined} />
            <Button onClick={changePassword} loading={savingPw} size="sm">Change Password</Button>
          </div>
        </Card>
      )}
    </div>
  )
}


type Tab = 'network' | 'notifications' | 'security'

export default function Settings() {
  const [tab, setTab] = useState<Tab>('network')
  const [settings, setSettings] = useState<AllSettings | null>(null)
  const [loading, setLoading] = useState(true)

  // Network
  const [dhcpStart, setDhcpStart] = useState('')
  const [dhcpEnd, setDhcpEnd] = useState('')
  const [interval, setInterval] = useState(5)

  // Telegram
  const [botToken, setBotToken] = useState('')
  const [chatId, setChatId] = useState('')
  const [telegramEnabled, setTelegramEnabled] = useState(false)
  const [testing, setTesting] = useState(false)

  // Security
  const [currentPw, setCurrentPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [savingPw, setSavingPw] = useState(false)

  const [saving, setSaving] = useState(false)
  const { logout } = useAuthStore()

  useEffect(() => {
    settingsApi.get().then((s) => {
      setSettings(s)
      setDhcpStart(s.dhcp_start)
      setDhcpEnd(s.dhcp_end)
      setInterval(s.scan_interval_minutes)
      setBotToken(s.telegram_bot_token)
      setChatId(s.telegram_chat_id)
      setTelegramEnabled(s.telegram_enabled)
    }).finally(() => setLoading(false))
  }, [])

  async function saveDhcp() {
    setSaving(true)
    try {
      await settingsApi.updateDhcp(dhcpStart, dhcpEnd)
      toast.success('DHCP range saved')
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? 'Failed to save')
    } finally { setSaving(false) }
  }

  async function saveSchedule() {
    setSaving(true)
    try {
      await settingsApi.updateScanSchedule(interval)
      toast.success('Scan schedule saved')
    } catch { toast.error('Failed to save') } finally { setSaving(false) }
  }

  async function saveTelegram() {
    setSaving(true)
    try {
      await settingsApi.updateTelegram({ telegram_bot_token: botToken, telegram_chat_id: chatId, telegram_enabled: telegramEnabled })
      toast.success('Telegram settings saved')
    } catch { toast.error('Failed to save') } finally { setSaving(false) }
  }

  async function testTelegram() {
    setTesting(true)
    try {
      await settingsApi.testTelegram()
      toast.success('Test message sent!')
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? 'Test failed')
    } finally { setTesting(false) }
  }

  async function changePassword() {
    if (newPw !== confirmPw) { toast.error('Passwords do not match'); return }
    if (newPw.length < 8) { toast.error('Password must be at least 8 characters'); return }
    setSavingPw(true)
    try {
      await authApi.changePassword(currentPw, newPw)
      toast.success('Password changed')
      setCurrentPw(''); setNewPw(''); setConfirmPw('')
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? 'Failed to change password')
    } finally { setSavingPw(false) }
  }

  if (loading) return <div className="flex justify-center py-16"><Spinner size="lg" /></div>

  return (
    <div className="max-w-2xl mx-auto flex flex-col gap-5">
      <h1 className="text-xl font-bold text-text-base">Settings</h1>

      {/* Tabs */}
      <div className="flex gap-1 bg-surface border border-border rounded-lg p-1 w-fit">
        {(['network', 'notifications', 'security'] as Tab[]).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors capitalize
              ${tab === t ? 'bg-surface2 text-text-base' : 'text-text-subtle hover:text-text-muted'}`}>
            {t}
          </button>
        ))}
      </div>

      {tab === 'network' && (
        <>
          <Card>
            <h2 className="text-sm font-semibold text-text-muted mb-4">DHCP Scan Range</h2>
            <div className="grid grid-cols-2 gap-4 mb-4">
              <Input label="Start IP" value={dhcpStart} onChange={(e) => setDhcpStart(e.target.value)} placeholder="192.168.1.1" />
              <Input label="End IP" value={dhcpEnd} onChange={(e) => setDhcpEnd(e.target.value)} placeholder="192.168.1.254" />
            </div>
            <Button onClick={saveDhcp} loading={saving} size="sm">Save Range</Button>
          </Card>

          <Card>
            <h2 className="text-sm font-semibold text-text-muted mb-4">Scan Schedule</h2>
            <div className="flex items-end gap-4">
              <div className="flex-1">
                <Input
                  label="Interval (minutes)"
                  type="number"
                  min={1}
                  max={1440}
                  value={interval}
                  onChange={(e) => setInterval(Number(e.target.value))}
                  hint="How often to scan the network automatically"
                />
              </div>
              <Button onClick={saveSchedule} loading={saving} size="sm">Save</Button>
            </div>
          </Card>
        </>
      )}

      {tab === 'notifications' && (
        <Card>
          <h2 className="text-sm font-semibold text-text-muted mb-1">Telegram Notifications</h2>
          <p className="text-xs text-text-subtle mb-4">
            Get notified on Telegram when new devices are detected.
            Create a bot via <span className="text-primary">@BotFather</span> and find your Chat ID via <span className="text-primary">@userinfobot</span>.
          </p>

          <div className="flex flex-col gap-4">
            <Input
              label="Bot Token"
              type="password"
              placeholder="1234567890:ABCdef..."
              value={botToken}
              onChange={(e) => setBotToken(e.target.value)}
            />
            <Input
              label="Chat ID"
              placeholder="-1001234567890 or 123456789"
              value={chatId}
              onChange={(e) => setChatId(e.target.value)}
            />

            <label className="flex items-center gap-3 cursor-pointer">
              <div
                onClick={() => setTelegramEnabled(!telegramEnabled)}
                className={`w-10 h-5 rounded-full transition-colors relative ${telegramEnabled ? 'bg-primary' : 'bg-surface2 border border-border'}`}
              >
                <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${telegramEnabled ? 'translate-x-5' : 'translate-x-0.5'}`} />
              </div>
              <span className="text-sm text-text-muted">Enable Telegram notifications</span>
            </label>

            <div className="flex gap-3">
              <Button onClick={saveTelegram} loading={saving} size="sm">Save Settings</Button>
              <Button variant="outline" onClick={testTelegram} loading={testing} size="sm">Send Test</Button>
            </div>
          </div>
        </Card>
      )}

      {tab === 'security' && (
        <Card>
          <h2 className="text-sm font-semibold text-text-muted mb-4">Change Password</h2>
          <div className="flex flex-col gap-4">
            <Input label="Current Password" type="password" value={currentPw} onChange={(e) => setCurrentPw(e.target.value)} />
            <Input label="New Password" type="password" placeholder="Minimum 8 characters" value={newPw} onChange={(e) => setNewPw(e.target.value)} />
            <Input label="Confirm New Password" type="password" value={confirmPw} onChange={(e) => setConfirmPw(e.target.value)}
              error={confirmPw && newPw !== confirmPw ? 'Passwords do not match' : undefined} />
            <Button onClick={changePassword} loading={savingPw} size="sm">Change Password</Button>
          </div>
        </Card>
      )}
    </div>
  )
}
