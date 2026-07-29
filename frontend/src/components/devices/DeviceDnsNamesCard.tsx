import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import type { Device } from '../../api/devices'
import { dnsNamesApi, type DeviceDnsName } from '../../api/dnsNames'
import { useI18n } from '../../i18n'
import { formatDateTime } from '../../utils/formatters'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import Card from '../ui/Card'
import Input from '../ui/Input'

export default function DeviceDnsNamesCard({ device, onChanged }: { device: Device; onChanged: () => void }) {
  const { t } = useI18n()
  const [enabled, setEnabled] = useState(false)
  const [names, setNames] = useState<DeviceDnsName[]>([])
  const [mode, setMode] = useState<'automatic' | 'manual' | 'discovered'>(
    (device.preferred_name_mode as 'automatic' | 'manual' | 'discovered') || 'automatic',
  )
  const [name, setName] = useState(device.preferred_name || '')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  async function load(refresh = false) {
    setLoading(true)
    try {
      const config = await dnsNamesApi.getConfig()
      setEnabled(config.dns_names_enabled)
      if (config.dns_names_enabled) setNames(await dnsNamesApi.listDeviceNames(device.id, refresh))
    } catch {
      setEnabled(false)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [device.id])

  async function savePreferred() {
    setSaving(true)
    try {
      await dnsNamesApi.setPreferred(device.id, mode, mode === 'automatic' ? undefined : name)
      toast.success(t('dns_preferred_name_saved'))
      onChanged()
    } catch {
      toast.error(t('save_failed'))
    } finally {
      setSaving(false)
    }
  }

  if (loading || !enabled) return null

  return (
    <Card>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-text-base">{t('dns_names_title')}</h2>
          <p className="text-sm text-text-subtle">{t('dns_names_description')}</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => load(true)}>{t('dns_refresh_names')}</Button>
      </div>

      <div className="mb-5 grid gap-3 md:grid-cols-[12rem_minmax(0,1fr)_auto]">
        <select
          className="input-field"
          value={mode}
          onChange={(event) => {
            const next = event.target.value as typeof mode
            setMode(next)
            if (next === 'automatic') setName('')
          }}
        >
          <option value="automatic">{t('dns_name_mode_automatic')}</option>
          <option value="discovered">{t('dns_name_mode_discovered')}</option>
          <option value="manual">{t('dns_name_mode_manual')}</option>
        </select>
        {mode === 'discovered' ? (
          <select className="input-field" value={name} onChange={(event) => setName(event.target.value)}>
            <option value="">{t('dns_select_name')}</option>
            {names.map((row) => <option key={row.id} value={row.name}>{row.name}</option>)}
          </select>
        ) : mode === 'manual' ? (
          <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="system.example.local" />
        ) : (
          <div className="input-field text-text-subtle">{device.hostname || device.ip_address || device.mac_address}</div>
        )}
        <Button onClick={savePreferred} loading={saving}>{t('save')}</Button>
      </div>

      {names.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border p-4 text-sm text-text-subtle">{t('dns_no_names')}</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="min-w-full text-sm">
            <thead className="bg-surface2 text-left text-xs uppercase tracking-wide text-text-subtle">
              <tr>
                <th className="px-3 py-2">{t('name')}</th>
                <th className="px-3 py-2">{t('dns_record_type')}</th>
                <th className="px-3 py-2">{t('dns_source')}</th>
                <th className="px-3 py-2">{t('col_status')}</th>
                <th className="px-3 py-2">{t('last_seen')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {names.map((row) => (
                <tr key={row.id}>
                  <td className="px-3 py-2">
                    <p className="font-mono text-text-base">{row.name}</p>
                    {row.canonical_name && <p className="text-xs text-text-subtle">→ {row.canonical_name}</p>}
                  </td>
                  <td className="px-3 py-2 text-text-muted">{row.record_type}</td>
                  <td className="px-3 py-2 text-text-muted">{row.source}</td>
                  <td className="px-3 py-2"><Badge variant={row.status === 'conflicting' ? 'warning' : 'success'}>{row.status}</Badge></td>
                  <td className="px-3 py-2 text-text-muted">{formatDateTime(row.last_seen)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
