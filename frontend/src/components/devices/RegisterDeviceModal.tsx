import { useState } from 'react'
import toast from 'react-hot-toast'
import { Device, devicesApi } from '../../api/devices'
import { formatMac } from '../../utils/formatters'
import Button from '../ui/Button'
import Input from '../ui/Input'
import Modal from '../ui/Modal'
import DeviceClassIcon, { DEVICE_CLASSES } from './DeviceClassIcon'
import { useI18n } from '../../i18n'

interface Props {
  device: Device | null
  onClose: () => void
  onSaved: (updated: Device) => void
}

export default function RegisterDeviceModal({ device, onClose, onSaved }: Props) {
  const { t } = useI18n()
  const [label, setLabel] = useState(device?.label ?? '')
  const [deviceClass, setDeviceClass] = useState(device?.device_class ?? 'Unknown')
  const [purpose, setPurpose] = useState(device?.purpose ?? '')
  const [location, setLocation] = useState(device?.location ?? '')
  const [passwordLocation, setPasswordLocation] = useState(device?.password_location ?? '')
  const [notes, setNotes] = useState(device?.notes ?? '')
  const [saving, setSaving] = useState(false)

  if (!device) return null

  async function handleSave() {
    if (!label.trim()) { toast.error(t('please_enter_label')); return }
    setSaving(true)
    try {
      const updated = await devicesApi.update(device!.id, {
        label: label.trim(),
        device_class: deviceClass,
        purpose: purpose.trim() || undefined,
        location: location.trim() || undefined,
        password_location: passwordLocation.trim() || undefined,
        notes: notes.trim() || undefined,
        is_registered: true,
      })
      toast.success(t('device_registered_success'))
      onSaved(updated)
      onClose()
    } catch {
      toast.error(t('failed_to_save_device'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open onClose={onClose} title={t('register_device_title')}>
      {/* Device info (read-only) */}
      <div className="bg-surface2 rounded-lg p-3 mb-4 grid grid-cols-2 gap-2 text-xs">
        <div>
          <p className="text-text-subtle mb-0.5">{t('mac_address')}</p>
          <p className="font-mono text-text-muted">{formatMac(device.mac_address)}</p>
        </div>
        <div>
          <p className="text-text-subtle mb-0.5">{t('ip_address')}</p>
          <p className="font-mono text-text-muted">{device.ip_address ?? '—'}</p>
        </div>
        <div>
          <p className="text-text-subtle mb-0.5">{t('vendor')}</p>
          <p className="text-text-muted">{device.vendor ?? t('unknown')}</p>
        </div>
        <div>
          <p className="text-text-subtle mb-0.5">{t('hostname')}</p>
          <p className="text-text-muted">{device.hostname ?? '—'}</p>
        </div>
      </div>

      <div className="flex flex-col gap-4">
        <Input
          label={t('label_required')}
          placeholder={t('device_label_placeholder')}
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          autoFocus
        />

        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-text-muted">{t('device_class')}</label>
          <div className="grid grid-cols-3 gap-2">
            {DEVICE_CLASSES.map((cls) => (
              <button
                key={cls}
                onClick={() => setDeviceClass(cls)}
                className={`flex items-center gap-2 p-2.5 rounded-lg border text-xs font-medium transition-colors
                  ${deviceClass === cls
                    ? 'border-primary bg-primary-dim text-primary'
                    : 'border-border bg-surface2 text-text-muted hover:border-primary/50'
                  }`}
              >
                <DeviceClassIcon deviceClass={cls} className="w-4 h-4" />
                {cls}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Input
            label={t('purpose')}
            placeholder={t('purpose_placeholder')}
            value={purpose}
            onChange={(e) => setPurpose(e.target.value)}
          />
          <Input
            label={t('location')}
            placeholder={t('location_placeholder')}
            value={location}
            onChange={(e) => setLocation(e.target.value)}
          />
        </div>

        <Input
          label={t('password_location')}
          placeholder="e.g. Vaultwarden → Servers"
          value={passwordLocation}
          onChange={(e) => setPasswordLocation(e.target.value)}
        />

        <Input
          label={t('notes')}
          placeholder={t('notes_optional_placeholder')}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />

        <div className="flex gap-3 justify-end pt-1">
          <Button variant="ghost" onClick={onClose}>{t('cancel')}</Button>
          <Button onClick={handleSave} loading={saving}>{t('register_device_title')}</Button>
        </div>
      </div>
    </Modal>
  )
}
