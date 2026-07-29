import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { credentialsApi, type Credential } from '../../api/credentials'
import { dnsNamesApi, type MicrosoftDnsConfig } from '../../api/dnsNames'
import { useI18n } from '../../i18n'
import Button from '../ui/Button'
import Card from '../ui/Card'
import Input from '../ui/Input'

const EMPTY: MicrosoftDnsConfig = {
  dns_names_enabled: false,
  enabled: false,
  server: '',
  zones: [],
  credential_id: null,
  interval_minutes: 60,
  last_sync_at: null,
  last_error: '',
}

export default function DnsNamesSettingsCard() {
  const { t } = useI18n()
  const [config, setConfig] = useState<MicrosoftDnsConfig>(EMPTY)
  const [credentials, setCredentials] = useState<Credential[]>([])
  const [zonesText, setZonesText] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    Promise.all([dnsNamesApi.getConfig(), credentialsApi.list().then((response) => response.data)])
      .then(([loaded, creds]) => {
        setConfig(loaded)
        setZonesText(loaded.zones.join('\n'))
        setCredentials(creds.filter((credential) => credential.credential_type === 'windows_winrm'))
      })
      .catch(() => toast.error(t('dns_config_load_failed')))
  }, [])

  const payload = () => ({
    dns_names_enabled: config.dns_names_enabled,
    enabled: config.enabled,
    server: config.server,
    zones: zonesText.split(/\r?\n|,/).map((zone) => zone.trim()).filter(Boolean),
    credential_id: config.credential_id,
    interval_minutes: config.interval_minutes,
  })

  async function save() {
    setBusy(true)
    try {
      const updated = await dnsNamesApi.updateConfig(payload())
      setConfig(updated)
      setZonesText(updated.zones.join('\n'))
      toast.success(t('dns_config_saved'))
    } catch {
      toast.error(t('save_failed'))
    } finally {
      setBusy(false)
    }
  }

  async function test() {
    setBusy(true)
    try {
      const result = await dnsNamesApi.test(payload())
      toast.success(t('dns_test_success', { records: result.records }))
    } catch {
      toast.error(t('dns_test_failed'))
    } finally {
      setBusy(false)
    }
  }

  async function sync() {
    setBusy(true)
    try {
      const result = await dnsNamesApi.sync()
      toast.success(t('dns_sync_success', { names: result.names, devices: result.devices }))
      setConfig(await dnsNamesApi.getConfig())
    } catch {
      toast.error(t('dns_sync_failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-text-base">{t('dns_settings_title')}</h2>
        <p className="text-sm text-text-subtle">{t('dns_settings_description')}</p>
      </div>
      <div className="space-y-4">
        <label className="flex items-start gap-3">
          <input type="checkbox" checked={config.dns_names_enabled} onChange={(event) => setConfig({ ...config, dns_names_enabled: event.target.checked })} />
          <span><span className="block text-sm text-text-base">{t('dns_enable_names')}</span><span className="text-xs text-text-subtle">{t('dns_enable_names_hint')}</span></span>
        </label>
        <label className="flex items-start gap-3">
          <input type="checkbox" checked={config.enabled} disabled={!config.dns_names_enabled} onChange={(event) => setConfig({ ...config, enabled: event.target.checked })} />
          <span><span className="block text-sm text-text-base">{t('dns_enable_microsoft')}</span><span className="text-xs text-text-subtle">{t('dns_enable_microsoft_hint')}</span></span>
        </label>
        <div className="grid gap-4 md:grid-cols-2">
          <Input label={t('dns_server')} value={config.server} disabled={!config.enabled} onChange={(event) => setConfig({ ...config, server: event.target.value })} placeholder="dns01.example.local" />
          <div>
            <label className="mb-1 block text-sm text-text-subtle">{t('dns_winrm_credential')}</label>
            <select className="input-field" disabled={!config.enabled} value={config.credential_id || ''} onChange={(event) => setConfig({ ...config, credential_id: Number(event.target.value) || null })}>
              <option value="">{t('dns_select_credential')}</option>
              {credentials.map((credential) => <option key={credential.id} value={credential.id}>{credential.name}</option>)}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-sm text-text-subtle">{t('dns_zones')}</label>
            <textarea className="input-field min-h-24 resize-y" disabled={!config.enabled} value={zonesText} onChange={(event) => setZonesText(event.target.value)} placeholder={'example.local\n0.168.192.in-addr.arpa'} />
            <p className="mt-1 text-xs text-text-subtle">{t('dns_zones_hint')}</p>
          </div>
          <Input type="number" min="5" max="1440" label={t('dns_sync_interval')} disabled={!config.enabled} value={String(config.interval_minutes)} onChange={(event) => setConfig({ ...config, interval_minutes: Number(event.target.value) || 60 })} />
        </div>
        {config.last_error && <p className="rounded-lg border border-danger/30 bg-danger/10 p-3 text-xs text-danger">{config.last_error}</p>}
        <div className="flex flex-wrap gap-2">
          <Button onClick={save} loading={busy}>{t('save_changes')}</Button>
          <Button variant="outline" onClick={test} disabled={!config.enabled} loading={busy}>{t('test_connection')}</Button>
          <Button variant="outline" onClick={sync} disabled={!config.enabled} loading={busy}>{t('dns_sync_now')}</Button>
        </div>
      </div>
    </Card>
  )
}
