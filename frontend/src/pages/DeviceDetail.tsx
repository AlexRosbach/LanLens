import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import toast from 'react-hot-toast'
import { Device, devicesApi } from '../api/devices'
import ConnectButtons from '../components/devices/ConnectButtons'
import DeviceClassIcon, { DEVICE_CLASSES } from '../components/devices/DeviceClassIcon'
import ServicesList from '../components/devices/ServicesList'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import Input from '../components/ui/Input'
import Spinner from '../components/ui/Spinner'
import { formatDateTime, formatMac, formatRelativeTime } from '../utils/formatters'

interface EditState {
  label: string
  deviceClass: string
  purpose: string
  description: string
  location: string
  responsible: string
  passwordLocation: string
  osInfo: string
  assetTag: string
  notes: string
}

function toEditState(d: Device): EditState {
  return {
    label: d.label ?? '',
    deviceClass: d.device_class,
    purpose: d.purpose ?? '',
    description: d.description ?? '',
    location: d.location ?? '',
    responsible: d.responsible ?? '',
    passwordLocation: d.password_location ?? '',
    osInfo: d.os_info ?? '',
    assetTag: d.asset_tag ?? '',
    notes: d.notes ?? '',
  }
}

function InfoRow({ label, value, mono = false }: { label: string; value?: string | null; mono?: boolean }) {
  if (!value) return null
  return (
    <div>
      <p className="text-text-subtle text-xs mb-0.5">{label}</p>
      <p className={`text-text-muted text-xs ${mono ? 'font-mono' : ''}`}>{value}</p>
    </div>
  )
}

export default function DeviceDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [device, setDevice] = useState<Device | null>(null)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState<EditState | null>(null)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    if (!id) return
    devicesApi.get(Number(id)).then((d) => {
      setDevice(d)
      setForm(toEditState(d))
    }).finally(() => setLoading(false))
  }, [id])

  function field(key: keyof EditState) {
    return {
      value: form?.[key] ?? '',
      onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
        setForm((f) => f ? { ...f, [key]: e.target.value } : f),
    }
  }

  async function handleSave() {
    if (!device || !form) return
    setSaving(true)
    try {
      const updated = await devicesApi.update(device.id, {
        label: form.label.trim() || undefined,
        device_class: form.deviceClass,
        purpose: form.purpose.trim() || undefined,
        description: form.description.trim() || undefined,
        location: form.location.trim() || undefined,
        responsible: form.responsible.trim() || undefined,
        password_location: form.passwordLocation.trim() || undefined,
        os_info: form.osInfo.trim() || undefined,
        asset_tag: form.assetTag.trim() || undefined,
        notes: form.notes.trim() || undefined,
        is_registered: true,
      })
      setDevice(updated)
      setForm(toEditState(updated))
      setEditing(false)
      toast.success('Device updated')
    } catch {
      toast.error('Failed to save')
    } finally {
      setSaving(false)
    }
  }

  function handleCancelEdit() {
    if (device) setForm(toEditState(device))
    setEditing(false)
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
  if (!device || !form) return <p className="text-text-muted">Device not found.</p>

  const hasDocumentation = device.purpose || device.description || device.location ||
    device.responsible || device.password_location || device.os_info || device.asset_tag || device.notes

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
        <ConnectButtons device={device} onScanRequested={() => devicesApi.get(device.id).then(setDevice)} />
      </Card>

      {/* Identity & Documentation */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-text-muted">Documentation</h2>
          {!editing ? (
            <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>Edit</Button>
          ) : (
            <div className="flex gap-2">
              <Button variant="ghost" size="sm" onClick={handleCancelEdit}>Cancel</Button>
              <Button size="sm" onClick={handleSave} loading={saving}>Save</Button>
            </div>
          )}
        </div>

        {editing ? (
          <div className="flex flex-col gap-4">
            {/* Identity */}
            <div className="grid grid-cols-2 gap-3">
              <Input label="Label / Name" placeholder="e.g. Proxmox Host" {...field('label')} />
              <Input label="Asset Tag" placeholder="e.g. SRV-001" {...field('assetTag')} />
            </div>

            <div className="flex flex-col gap-1">
              <label className="text-sm font-medium text-text-muted">Device Class</label>
              <div className="grid grid-cols-3 gap-2">
                {DEVICE_CLASSES.map((cls) => (
                  <button key={cls}
                    onClick={() => setForm((f) => f ? { ...f, deviceClass: cls } : f)}
                    className={`flex items-center gap-2 p-2 rounded-lg border text-xs font-medium transition-colors
                      ${form.deviceClass === cls
                        ? 'border-primary bg-primary-dim text-primary'
                        : 'border-border bg-surface2 text-text-muted hover:border-primary/50'}`}>
                    <DeviceClassIcon deviceClass={cls} className="w-4 h-4" />
                    {cls}
                  </button>
                ))}
              </div>
            </div>

            {/* Documentation fields */}
            <div className="border-t border-border pt-4 grid grid-cols-2 gap-3">
              <Input label="Purpose" placeholder="e.g. Virtualisation host" {...field('purpose')} />
              <Input label="Location" placeholder="e.g. Server rack, Shelf 2" {...field('location')} />
              <Input label="Responsible" placeholder="e.g. IT Admin" {...field('responsible')} />
              <Input label="OS / Firmware" placeholder="e.g. Proxmox VE 8.2" {...field('osInfo')} />
              <div className="col-span-2">
                <Input label="Password Location" placeholder="e.g. Vaultwarden → Servers" {...field('passwordLocation')} />
              </div>
            </div>

            <div className="flex flex-col gap-1">
              <label className="text-sm font-medium text-text-muted">Description</label>
              <textarea
                rows={2}
                className="input-field resize-none"
                placeholder="What does this device do?"
                {...field('description')}
              />
            </div>

            <div className="flex flex-col gap-1">
              <label className="text-sm font-medium text-text-muted">Notes</label>
              <textarea
                rows={2}
                className="input-field resize-none"
                placeholder="Additional notes…"
                {...field('notes')}
              />
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {/* Network identity */}
            <div className="grid grid-cols-2 gap-x-8 gap-y-3 text-sm">
              <InfoRow label="MAC Address" value={formatMac(device.mac_address)} mono />
              <InfoRow label="IP Address" value={device.ip_address} mono />
              <InfoRow label="Hostname" value={device.hostname} mono />
              <InfoRow label="Vendor" value={device.vendor} />
              <InfoRow label="Asset Tag" value={device.asset_tag} />
              <InfoRow label="OS / Firmware" value={device.os_info} />
              <div>
                <p className="text-text-subtle text-xs mb-0.5">First Seen</p>
                <p className="text-text-muted text-xs">{formatDateTime(device.first_seen)}</p>
              </div>
              <div>
                <p className="text-text-subtle text-xs mb-0.5">Last Seen</p>
                <p className="text-text-muted text-xs">{formatRelativeTime(device.last_seen)}</p>
              </div>
            </div>

            {/* Documentation fields */}
            {hasDocumentation && (
              <div className="border-t border-border pt-4 grid grid-cols-2 gap-x-8 gap-y-3 text-sm">
                <InfoRow label="Purpose" value={device.purpose} />
                <InfoRow label="Location" value={device.location} />
                <InfoRow label="Responsible" value={device.responsible} />
                <InfoRow label="Password Location" value={device.password_location} />
                {device.description && (
                  <div className="col-span-2">
                    <p className="text-text-subtle text-xs mb-0.5">Description</p>
                    <p className="text-text-muted text-xs whitespace-pre-wrap">{device.description}</p>
                  </div>
                )}
                {device.notes && (
                  <div className="col-span-2">
                    <p className="text-text-subtle text-xs mb-0.5">Notes</p>
                    <p className="text-text-muted text-xs whitespace-pre-wrap">{device.notes}</p>
                  </div>
                )}
              </div>
            )}

            {!hasDocumentation && (
              <p className="text-xs text-text-subtle border-t border-border pt-3">
                No documentation yet — click <strong>Edit</strong> to add purpose, location, responsible, and more.
              </p>
            )}
          </div>
        )}
      </Card>

      {/* Services */}
      <Card>
        <h2 className="text-sm font-semibold text-text-muted mb-3">Services</h2>
        <ServicesList
          deviceId={device.id}
          services={device.services}
          onChange={(services) => setDevice({ ...device, services })}
        />
      </Card>

      {/* Open Ports */}
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
          Removing this device will delete all port scan history and services documentation. The device will reappear automatically on the next network scan.
        </p>
        <Button variant="danger" size="sm" loading={deleting} onClick={handleDelete}>
          Remove Device
        </Button>
      </Card>
    </div>
  )
}
