import { useState } from 'react'
import toast from 'react-hot-toast'
import type { Credential } from '../../api/credentials'
import type { DeepScanConfig, ScanProfile } from '../../api/deepScan'
import { deepScanApi } from '../../api/deepScan'
import Button from '../ui/Button'
import Input from '../ui/Input'
import { useI18n } from '../../i18n'

const PROFILES: { value: ScanProfile; labelKey: string }[] = [
  { value: 'hardware_only',        labelKey: 'deep_scan_profile_hardware_only' },
  { value: 'os_services',          labelKey: 'deep_scan_profile_os_services' },
  { value: 'linux_container_host', labelKey: 'deep_scan_profile_linux_container_host' },
  { value: 'windows_audit',        labelKey: 'deep_scan_profile_windows_audit' },
  { value: 'hypervisor_inventory', labelKey: 'deep_scan_profile_hypervisor_inventory' },
  { value: 'full',                 labelKey: 'deep_scan_profile_full' },
]

interface Props {
  deviceId: number
  config: DeepScanConfig
  credentials: Credential[]
  onSaved: (config: DeepScanConfig) => void
}

export default function DeepScanConfigForm({ deviceId, config, credentials, onSaved }: Props) {
  const { t } = useI18n()

  const [enabled, setEnabled] = useState(config.enabled)
  const [credentialId, setCredentialId] = useState<number | null>(config.credential_id)
  const [profile, setProfile] = useState<ScanProfile>(config.scan_profile)
  const [autoEnabled, setAutoEnabled] = useState(config.auto_scan_enabled)
  const [interval, setInterval] = useState(config.interval_minutes)
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      const resp = await deepScanApi.updateConfig(deviceId, {
        enabled,
        credential_id: credentialId,
        scan_profile: profile,
        auto_scan_enabled: autoEnabled,
        interval_minutes: interval,
      })
      onSaved(resp.data)
      toast.success(t('deep_scan_save_config') + ' ✓')
    } catch {
      toast.error(t('failed_to_save_configuration'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="border border-border rounded-xl p-4 bg-surface2 space-y-4">
      {/* Enable toggle */}
      <label className="flex items-center justify-between cursor-pointer">
        <span className="text-sm font-medium text-text-base">
          {t('deep_scan')} {t('enabled') || 'enabled'}
        </span>
        <button
          type="button"
          onClick={() => setEnabled(!enabled)}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
            enabled ? 'bg-primary' : 'bg-surface2 border border-border'
          }`}
        >
          <span
            className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
              enabled ? 'translate-x-6' : 'translate-x-1'
            }`}
          />
        </button>
      </label>

      {/* Credential selector */}
      <div className="flex flex-col gap-1">
        <label className="text-sm font-medium text-text-muted">{t('deep_scan_credential')}</label>
        <select
          className="input-field"
          value={credentialId ?? ''}
          onChange={(e) => setCredentialId(e.target.value ? Number(e.target.value) : null)}
        >
          <option value="">{t('deep_scan_no_credential')}</option>
          {credentials.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} ({c.username} — {c.credential_type === 'linux_ssh' ? t('credential_type_linux_ssh') : t('credential_type_windows_winrm')})
            </option>
          ))}
        </select>
      </div>

      {/* Profile selector */}
      <div className="flex flex-col gap-1">
        <label className="text-sm font-medium text-text-muted">{t('deep_scan_profile')}</label>
        <select
          className="input-field"
          value={profile}
          onChange={(e) => setProfile(e.target.value as ScanProfile)}
        >
          {PROFILES.map((p) => (
            <option key={p.value} value={p.value}>
              {t(p.labelKey as Parameters<typeof t>[0])}
            </option>
          ))}
        </select>
      </div>

      {/* Auto scan toggle */}
      <label className="flex items-center justify-between cursor-pointer">
        <span className="text-sm font-medium text-text-base">{t('deep_scan_auto_enabled')}</span>
        <button
          type="button"
          onClick={() => setAutoEnabled(!autoEnabled)}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
            autoEnabled ? 'bg-primary' : 'bg-surface2 border border-border'
          }`}
        >
          <span
            className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
              autoEnabled ? 'translate-x-6' : 'translate-x-1'
            }`}
          />
        </button>
      </label>

      {/* Interval */}
      {autoEnabled && (
        <Input
          label={t('deep_scan_interval')}
          type="number"
          min={5}
          value={interval}
          onChange={(e) => {
            const parsed = parseInt(e.target.value, 10)
            setInterval(Number.isFinite(parsed) ? Math.max(5, parsed) : 5)
          }}
        />
      )}

      <Button onClick={handleSave} loading={saving} size="sm">
        {t('deep_scan_save_config')}
      </Button>
    </div>
  )
}
