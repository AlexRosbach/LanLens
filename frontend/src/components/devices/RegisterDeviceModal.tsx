import { useState } from 'react'
import toast from 'react-hot-toast'
import { Device, devicesApi } from '../../api/devices'
import { formatMac } from '../../utils/formatters'
import Button from '../ui/Button'
import Input from '../ui/Input'
import Modal from '../ui/Modal'
import DeviceClassIcon, { DEVICE_CLASSES } from './DeviceClassIcon'

interface Props {
  device: Device | null
  onClose: () => void
  onSaved: (updated: Device) => void
}

export default function RegisterDeviceModal({ device, onClose, onSaved }: Props) {
  const [label, setLabel] = useState(device?.label ?? '')
  const [deviceClass, setDeviceClass] = useState(device?.device_class ?? 'Unknown')
  const [notes, setNotes] = useState(device?.notes ?? '')
  const [saving, setSaving] = useState(false)

  if (!device) return null

  async function handleSave() {
    if (!label.trim()) { toast.error('Please enter a label'); return }
    setSaving(true)
    try {
      const updated = await devicesApi.update(device!.id, {
        label: label.trim(),
        device_class: deviceClass,
        notes: notes.trim() || undefined,
        is_registered: true,
      })
      toast.success('Device registered')
      onSaved(updated)
      onClose()
    } catch {
      toast.error('Failed to save device')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open onClose={onClose} title="Register Device">
      {/* Device info (read-only) */}
      <div className="bg-surface2 rounded-lg p-3 mb-4 grid grid-cols-2 gap-2 text-xs">
        <div>
          <p className="text-text-subtle mb-0.5">MAC Address</p>
          <p className="font-mono text-text-muted">{formatMac(device.mac_address)}</p>
        </div>
        <div>
          <p className="text-text-subtle mb-0.5">IP Address</p>
          <p className="font-mono text-text-muted">{device.ip_address ?? '—'}</p>
        </div>
        <div>
          <p className="text-text-subtle mb-0.5">Vendor</p>
          <p className="text-text-muted">{device.vendor ?? 'Unknown'}</p>
        </div>
        <div>
          <p className="text-text-subtle mb-0.5">Hostname</p>
          <p className="text-text-muted">{device.hostname ?? '—'}</p>
        </div>
      </div>

      <div className="flex flex-col gap-4">
        <Input
          label="Label *"
          placeholder="e.g. NAS Server, Living Room Pi"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          autoFocus
        />

        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-text-muted">Device Class</label>
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

        <Input
          label="Notes"
          placeholder="Optional notes about this device"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />

        <div className="flex gap-3 justify-end pt-1">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={handleSave} loading={saving}>Register Device</Button>
        </div>
      </div>
    </Modal>
  )
}
