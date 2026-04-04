import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import toast from 'react-hot-toast'
import { Device, devicesApi } from '../api/devices'
import ConnectButtons from '../components/devices/ConnectButtons'
import DeviceClassIcon, { DEVICE_CLASSES } from '../components/devices/DeviceClassIcon'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import Input from '../components/ui/Input'
import Spinner from '../components/ui/Spinner'
import { formatDateTime, formatMac, formatRelativeTime } from '../utils/formatters'

export default function DeviceDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [device, setDevice] = useState<Device | null>(null)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(false)
  const [label, setLabel] = useState('')
  const [deviceClass, setDeviceClass] = useState('')
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    if (!id) return
    devicesApi.get(Number(id)).then((d) => {
      setDevice(d)
      setLabel(d.label ?? '')
      setDeviceClass(d.device_class)
      setNotes(d.notes ?? '')
    }).finally(() => setLoading(false))
  }, [id])

  async function handleSave() {
    if (!device) return
    setSaving(true)
    try {
      const updated = await devicesApi.update(device.id, {
        label: label.trim() || undefined,
        device_class: deviceClass,
        notes: notes.trim() || undefined,
        is_registered: !!label.trim(),
      })
      setDevice(updated)
      setEditing(false)
      toast.success('Device updated')
    } catch {
      toast.error('Failed to save')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (!device || !confirm('Delete this device? It will reappear on next scan.')) return
    setDeleting(true)
    try {
      await devicesApi.delete(device.id)
      toast.success('Device removed')
      navigate('/')
    } catch {
      toast.error('Failed to delete')
      setDeleting(false)
    }
  }

  if (loading) return <div className="flex justify-center py-16"><Spinner size="lg" /></div>
  if (!device) return <p className="text-text-muted">Device not found.</p>

  return (
    <div className="max-w-3xl mx-auto flex flex-col gap-5">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-4">
          <button onClick={() => navigate('/')} className="text-text-subtle hover:text-text-base transition-colors">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <div className="w-10 h-10 rounded-xl bg-surface2 border border-border flex items-center justify-center">
            <DeviceClassIcon deviceClass={device.device_class} className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-text-base">{device.label ?? device.mac_address}</h1>
            <p className="text-sm text-text-muted">{device.device_class} · {device.vendor ?? 'Unknown vendor'}</p>
          </div>
        </div>
        <Badge variant={device.is_online ? 'success' : 'danger'} dot>
          {device.is_online ? 'Online' : 'Offline'}
        </Badge>
      </div>

      {/* Connect */}
      <Card>
        <h2 className="text-sm font-semibold text-text-muted mb-3">Connect</h2>
        <ConnectButtons device={device} onScanRequested={() => {
          devicesApi.get(device.id).then(setDevice)
        }} />
      </Card>

      {/* Device info */}
      <Card>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-text-muted">Device Info</h2>
          {!editing ? (
            <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>Edit</Button>
          ) : (
            <div className="flex gap-2">
              <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>Cancel</Button>
              <Button size="sm" onClick={handleSave} loading={saving}>Save</Button>
            </div>
          )}
        </div>

        {editing ? (
          <div className="flex flex-col gap-4">
            <Input label="Label" value={label} onChange={(e) => setLabel(e.target.value)} />
            <div className="flex flex-col gap-1">
              <label className="text-sm font-medium text-text-muted">Device Class</label>
              <div className="grid grid-cols-3 gap-2">
                {DEVICE_CLASSES.map((cls) => (
                  <button key={cls}
                    onClick={() => setDeviceClass(cls)}
                    className={`flex items-center gap-2 p-2 rounded-lg border text-xs font-medium transition-colors
                      ${deviceClass === cls ? 'border-primary bg-primary-dim text-primary' : 'border-border bg-surface2 text-text-muted hover:border-primary/50'}`}>
                    <DeviceClassIcon deviceClass={cls} className="w-4 h-4" />
                    {cls}
                  </button>
                ))}
              </div>
            </div>
            <Input label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-x-8 gap-y-3 text-sm">
            {[
              ['MAC Address', formatMac(device.mac_address)],
              ['IP Address', device.ip_address ?? '—'],
              ['Hostname', device.hostname ?? '—'],
              ['Vendor', device.vendor ?? '—'],
              ['First Seen', formatDateTime(device.first_seen)],
              ['Last Seen', formatRelativeTime(device.last_seen)],
            ].map(([k, v]) => (
              <div key={k}>
                <p className="text-text-subtle text-xs mb-0.5">{k}</p>
                <p className="text-text-muted font-mono text-xs">{v}</p>
              </div>
            ))}
            {device.notes && (
              <div className="col-span-2">
                <p className="text-text-subtle text-xs mb-0.5">Notes</p>
                <p className="text-text-muted text-xs">{device.notes}</p>
              </div>
            )}
          </div>
        )}
      </Card>

      {/* Ports */}
      {device.latest_scan && (
        <Card>
          <h2 className="text-sm font-semibold text-text-muted mb-3">
            Open Ports
            <span className="ml-2 text-xs font-normal text-text-subtle">
              (scanned {formatRelativeTime(device.latest_scan.scanned_at)})
            </span>
          </h2>
          {device.latest_scan.open_ports.length === 0 ? (
            <p className="text-sm text-text-subtle">No open ports found</p>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {device.latest_scan.open_ports.map((p) => (
                <div key={`${p.port}-${p.protocol}`}
                  className="flex items-center gap-2 bg-surface2 rounded-lg px-3 py-2 text-xs">
                  <span className="font-mono font-medium text-primary">{p.port}</span>
                  <span className="text-text-subtle">{p.protocol}</span>
                  <span className="text-text-muted ml-auto">{p.service}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {/* Danger zone */}
      <Card>
        <h2 className="text-sm font-semibold text-danger mb-2">Danger Zone</h2>
        <p className="text-xs text-text-subtle mb-3">
          Removing this device will delete all port scan history. The device will reappear automatically on the next network scan.
        </p>
        <Button variant="danger" size="sm" loading={deleting} onClick={handleDelete}>
          Remove Device
        </Button>
      </Card>
    </div>
  )
}
