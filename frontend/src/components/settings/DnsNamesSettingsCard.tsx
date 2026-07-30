import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { dnsNamesApi, type AxfrDnsConfig } from '../../api/dnsNames'
import { useI18n } from '../../i18n'
import Button from '../ui/Button'
import Card from '../ui/Card'
import Input from '../ui/Input'

const EMPTY: AxfrDnsConfig = {
  dns_names_enabled: false,
  enabled: false,
  server: '',
  zones: [],
  port: 53,
  timeout_seconds: 15,
  tsig_key_name: '',
  tsig_algorithm: 'hmac-sha256',
  tsig_configured: false,
  interval_minutes: 60,
  last_sync_at: null,
  last_error: '',
}

export default function DnsNamesSettingsCard() {
  const { t } = useI18n()
  const [config, setConfig] = useState<AxfrDnsConfig>(EMPTY)
  const [zonesText, setZonesText] = useState('')
  const [tsigSecret, setTsigSecret] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    dnsNamesApi.getConfig()
      .then((loaded) => {
        setConfig(loaded)
        setZonesText(loaded.zones.join('\n'))
      })
      .catch(() => toast.error(t('dns_config_load_failed')))
  }, [])

  const payload = () => ({
    dns_names_enabled: config.dns_names_enabled,
    enabled: config.enabled,
    server: config.server,
    zones: zonesText.split(/\r?\n|,/).map((zone) => zone.trim()).filter(Boolean),
    port: config.port,
    timeout_seconds: config.timeout_seconds,
    tsig_key_name: config.tsig_key_name,
    tsig_secret: tsigSecret || undefined,
    clear_tsig_secret: false,
    tsig_algorithm: config.tsig_algorithm,
    interval_minutes: config.interval_minutes,
  })

  async function save() {
    setBusy(true)
    try {
      const updated = await dnsNamesApi.updateConfig(payload())
      setConfig(updated)
      setZonesText(updated.zones.join('\n'))
      setTsigSecret('')
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
          <Input type="number" min="1" max="65535" label={t('dns_axfr_port')} disabled={!config.enabled} value={String(config.port)} onChange={(event) => setConfig({ ...config, port: Number(event.target.value) || 53 })} />
          <div>
            <label className="mb-1 block text-sm text-text-subtle">{t('dns_zones')}</label>
            <textarea className="input-field min-h-24 resize-y" disabled={!config.enabled} value={zonesText} onChange={(event) => setZonesText(event.target.value)} placeholder={'example.local\n0.168.192.in-addr.arpa'} />
            <p className="mt-1 text-xs text-text-subtle">{t('dns_zones_hint')}</p>
          </div>
          <div className="grid gap-4">
            <Input type="number" min="3" max="120" label={t('dns_axfr_timeout')} disabled={!config.enabled} value={String(config.timeout_seconds)} onChange={(event) => setConfig({ ...config, timeout_seconds: Number(event.target.value) || 15 })} />
            <Input type="number" min="5" max="1440" label={t('dns_sync_interval')} disabled={!config.enabled} value={String(config.interval_minutes)} onChange={(event) => setConfig({ ...config, interval_minutes: Number(event.target.value) || 60 })} />
          </div>
          <Input label={t('dns_tsig_key_name')} disabled={!config.enabled} value={config.tsig_key_name} onChange={(event) => setConfig({ ...config, tsig_key_name: event.target.value })} placeholder="lanlens-key.example.local" />
          <Input type="password" label={t('dns_tsig_secret')} disabled={!config.enabled} value={tsigSecret} onChange={(event) => setTsigSecret(event.target.value)} placeholder={config.tsig_configured ? t('dns_tsig_secret_stored') : t('dns_tsig_secret_optional')} />
          <div>
            <label className="mb-1 block text-sm text-text-subtle">{t('dns_tsig_algorithm')}</label>
            <select className="input-field" disabled={!config.enabled} value={config.tsig_algorithm} onChange={(event) => setConfig({ ...config, tsig_algorithm: event.target.value })}>
              <option value="hmac-sha256">HMAC-SHA256</option>
              <option value="hmac-sha384">HMAC-SHA384</option>
              <option value="hmac-sha512">HMAC-SHA512</option>
            </select>
          </div>
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
